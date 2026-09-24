"""The Awiros-ANPR-OCR recogniser as a PyTorch module.

The weights were trained in PaddlePaddle. PaddlePaddle has no Metal backend
and its Apple-silicon build runs on one CPU core (about 50 ms a plate on the
development machine); PyTorch runs the same network on the GPU there and on
CUDA in deployment, and is already the pipeline's runtime. So the network is
restated here - PP-OCRv5's PPHGNetV2_B4 backbone in its text-recognition
form, the SVTR sequence encoder and the CTC head, from PaddleOCR (Apache-2.0)
- with module names that match the checkpoint, and the published weights are
loaded into it unchanged. The NRTR branch is used only in training and is not
built.

`tests/unit/test_indian_ocr.py` pins the layer shapes against the
checkpoint; `tools/bench/ocr_compare.py --parity` compares the probabilities
with PaddlePaddle's own forward pass where it is installed.
"""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn

#: in, mid, out channels, blocks, light block, kernel, layers, downsample stride
STAGES = (
    (48, 48, 128, 1, False, 3, 6, (2, 1)),
    (128, 96, 512, 1, False, 3, 6, (1, 2)),
    (512, 192, 1024, 3, True, 5, 6, (2, 1)),
    (1024, 384, 2048, 1, True, 5, 6, (2, 1)),
)
NUM_CLASSES = 64


class ConvBNAct(nn.Module):
    def __init__(self, cin: int, cout: int, k: int = 3, stride=1, groups: int = 1,
                 act: bool = True, same: bool = False) -> None:
        super().__init__()
        # Paddle's "SAME" on an even kernel pads after, not before (TF rule).
        self.same = same
        self.conv = nn.Conv2d(cin, cout, k, stride, 0 if same else (k - 1) // 2,
                              groups=groups, bias=False)
        self.bn = nn.BatchNorm2d(cout, eps=1e-5)
        self.act = nn.ReLU() if act else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.same:
            x = F.pad(x, (0, 1, 0, 1))
        return self.act(self.bn(self.conv(x)))


class LightConvBNAct(nn.Module):
    def __init__(self, cin: int, cout: int, k: int) -> None:
        super().__init__()
        self.conv1 = ConvBNAct(cin, cout, 1, act=False)
        self.conv2 = ConvBNAct(cout, cout, k, groups=cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv2(self.conv1(x))


class StemBlock(nn.Module):
    def __init__(self, cin: int = 3, mid: int = 32, cout: int = 48) -> None:
        super().__init__()
        self.stem1 = ConvBNAct(cin, mid, 3, 2)
        self.stem2a = ConvBNAct(mid, mid // 2, 2, same=True)
        self.stem2b = ConvBNAct(mid // 2, mid, 2, same=True)
        self.stem3 = ConvBNAct(mid * 2, mid, 3, 1)          # stride 1 for text
        self.stem4 = ConvBNAct(mid, cout, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem1(x)
        x2 = self.stem2b(self.stem2a(x))
        x1 = F.max_pool2d(F.pad(x, (0, 1, 0, 1), value=float("-inf")), 2, 1)
        return self.stem4(self.stem3(torch.cat([x1, x2], 1)))


class HGV2Block(nn.Module):
    def __init__(self, cin: int, mid: int, cout: int, k: int, n: int,
                 identity: bool, light: bool) -> None:
        super().__init__()
        self.identity = identity
        self.layers = nn.ModuleList(
            (LightConvBNAct(cin if i == 0 else mid, mid, k) if light
             else ConvBNAct(cin if i == 0 else mid, mid, k)) for i in range(n))
        self.aggregation_squeeze_conv = ConvBNAct(cin + n * mid, cout // 2, 1)
        self.aggregation_excitation_conv = ConvBNAct(cout // 2, cout, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        outs = [x]
        y = x
        for layer in self.layers:
            y = layer(y)
            outs.append(y)
        y = self.aggregation_excitation_conv(self.aggregation_squeeze_conv(torch.cat(outs, 1)))
        return y + x if self.identity else y


class HGV2Stage(nn.Module):
    def __init__(self, cin, mid, cout, blocks, light, k, n, stride) -> None:
        super().__init__()
        self.downsample = ConvBNAct(cin, cin, 3, stride, groups=cin, act=False)
        self.blocks = nn.Sequential(*(
            HGV2Block(cin if i == 0 else cout, mid, cout, k, n, i > 0, light)
            for i in range(blocks)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.blocks(self.downsample(x))


class Backbone(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.stem = StemBlock()
        self.stages = nn.ModuleList(HGV2Stage(*cfg) for cfg in STAGES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem(x)
        for s in self.stages:
            x = s(x)
        return F.avg_pool2d(x, (3, 2))                      # (B, 2048, 1, 40)


class ConvBNSwish(nn.Module):
    def __init__(self, cin: int, cout: int, k=(1, 1)) -> None:
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, k, 1, (k[0] // 2, k[1] // 2), bias=False)
        self.norm = nn.BatchNorm2d(cout, eps=1e-5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.silu(self.norm(self.conv(x)))


class Attention(nn.Module):
    def __init__(self, dim: int, heads: int) -> None:
        super().__init__()
        self.heads, self.hd = heads, dim // heads
        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, N, C = x.shape
        q, k, v = self.qkv(x).reshape(B, N, 3, self.heads, self.hd).permute(2, 0, 3, 1, 4)
        attn = ((q * self.hd ** -0.5) @ k.transpose(-1, -2)).softmax(-1)
        return self.proj((attn @ v).transpose(1, 2).reshape(B, N, C))


class Mlp(nn.Module):
    def __init__(self, dim: int, hidden: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(F.silu(self.fc1(x)))


class SvtrBlock(nn.Module):
    def __init__(self, dim: int, heads: int = 8, mlp_ratio: float = 2.0) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-5)
        self.mixer = Attention(dim, heads)
        self.norm2 = nn.LayerNorm(dim, eps=1e-5)
        self.mlp = Mlp(dim, int(dim * mlp_ratio))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.mixer(self.norm1(x))
        return x + self.mlp(self.norm2(x))


class EncoderWithSVTR(nn.Module):
    def __init__(self, cin: int = 2048, dims: int = 120, depth: int = 2,
                 hidden: int = 120, k=(1, 3)) -> None:
        super().__init__()
        self.conv1 = ConvBNSwish(cin, cin // 8, k)
        self.conv2 = ConvBNSwish(cin // 8, hidden)
        self.svtr_block = nn.ModuleList(SvtrBlock(hidden) for _ in range(depth))
        self.norm = nn.LayerNorm(hidden, eps=1e-6)
        self.conv3 = ConvBNSwish(hidden, cin)
        self.conv4 = ConvBNSwish(2 * cin, cin // 8, k)
        self.conv1x1 = ConvBNSwish(cin // 8, dims)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = x
        z = self.conv2(self.conv1(x))
        B, C, H, W = z.shape
        z = z.flatten(2).transpose(1, 2)
        for blk in self.svtr_block:
            z = blk(z)
        z = self.norm(z).reshape(B, H, W, C).permute(0, 3, 1, 2)
        z = self.conv3(z)
        return self.conv1x1(self.conv4(torch.cat([h, z], 1)))


class _Seq(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.encoder = EncoderWithSVTR()


class _Fc(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc = nn.Linear(120, NUM_CLASSES)


class Head(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.ctc_encoder = _Seq()
        self.ctc_head = _Fc()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.ctc_encoder.encoder(x).squeeze(2).transpose(1, 2)      # (B, 40, 120)
        return self.ctc_head.fc(z).softmax(-1)


class AwirosRecogniser(nn.Module):
    """(B, 3, 48, 320) in [-1, 1] -> (B, 40, 64) character probabilities."""

    def __init__(self) -> None:
        super().__init__()
        self.backbone = Backbone()
        self.head = Head()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(x))


def paddle_to_torch(state: dict, model: nn.Module) -> dict[str, torch.Tensor]:
    """The checkpoint's tensors under this module's names and layouts.

    BatchNorm's running statistics are `_mean`/`_variance` in Paddle, and a
    Paddle Linear stores its weight (in, out) - transposed from PyTorch's.
    Tensors this module does not have (the NRTR branch, the backbone's
    classification head) are left out; a tensor it has that the checkpoint
    lacks is an error.
    """
    wanted = model.state_dict()
    linear = {n + ".weight" for n, m in model.named_modules() if isinstance(m, nn.Linear)}
    out: dict[str, torch.Tensor] = {}
    for k, v in state.items():
        name = k.replace("._mean", ".running_mean").replace("._variance", ".running_var")
        if name not in wanted:
            continue
        t = torch.as_tensor(v)
        if name in linear:
            t = t.T.contiguous()
        if tuple(t.shape) != tuple(wanted[name].shape):
            raise ValueError(f"{k}: checkpoint {tuple(t.shape)} != "
                             f"model {tuple(wanted[name].shape)}")
        out[name] = t
    missing = [k for k in wanted if k not in out and not k.endswith("num_batches_tracked")]
    if missing:
        raise ValueError(f"checkpoint is missing {len(missing)} tensors, e.g. {missing[:3]}")
    return out


def load(weights: Path, device: str = "cpu") -> AwirosRecogniser:
    from safetensors.numpy import load_file

    model = AwirosRecogniser()
    model.load_state_dict(paddle_to_torch(load_file(str(weights)), model), strict=False)
    return model.eval().to(device)
