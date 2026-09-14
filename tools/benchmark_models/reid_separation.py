"""Does a DINOv2 embedding separate real vehicles on the government feed?

Embeddings were dropped from the pipeline on a measurement taken against the
*synthetic* corpus. Real footage is a different question, and it decides whether
cross-camera re-identification is possible on this grid at all.

The test is the standard one: crops of the same vehicle should embed close
together, crops of different vehicles far apart. Tracks are built here by IoU
association rather than through the pipeline, so the measurement depends on as
little of our own code as possible.
"""
import collections
import itertools
import sys
from pathlib import Path

import av
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from saakshya.runtime.backend import quiet_transformers

quiet_transformers()
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, AutoModelForObjectDetection

CAM = sys.argv[1] if len(sys.argv) > 1 else "cam01"
FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 60
VEH = {"car", "truck", "bus", "motorbike", "motorcycle"}

dproc = AutoImageProcessor.from_pretrained("PekingU/rtdetr_v2_r18vd")
det = AutoModelForObjectDetection.from_pretrained("PekingU/rtdetr_v2_r18vd").eval()
names = det.config.id2label
eproc = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
enc = AutoModel.from_pretrained("facebook/dinov2-base").eval()


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


c = av.open(f"rtsp://103.250.160.189:8554/stream/{CAM}",
            options={"rtsp_transport": "tcp", "stimeout": "8000000"}, timeout=25)
tracks, live, nid, n = collections.defaultdict(list), [], 0, 0
for i, f in enumerate(c.decode(video=0)):
    if i % 5:
        continue
    img = f.to_ndarray(format="rgb24")
    with torch.no_grad():
        o = det(**dproc(images=img, return_tensors="pt"))
    r = dproc.post_process_object_detection(o, threshold=0.5,
                                            target_sizes=[img.shape[:2]])[0]
    boxes = [tuple(int(v) for v in box)
             for box, label in zip(r["boxes"], r["labels"], strict=True)
             if names[int(label)] in VEH]
    boxes = [b for b in boxes if b[2]-b[0] >= 60 and b[3]-b[1] >= 60]

    nxt = []
    for b in boxes:
        hit = max(((t, iou(b, tb)) for t, tb in live), key=lambda x: x[1],
                  default=(None, 0.0))
        tid = hit[0] if hit[1] > 0.35 else None
        if tid is None:
            nid += 1
            tid = nid
        nxt.append((tid, b))
        if len(tracks[tid]) < 6:
            crop = img[b[1]:b[3], b[0]:b[2]]
            if crop.size:
                tracks[tid].append(Image.fromarray(crop))
    live = nxt
    n += 1
    if n >= FRAMES:
        break
c.close()

usable = {k: v for k, v in tracks.items() if len(v) >= 3}
print(f"{CAM}: {n} frames sampled, {len(tracks)} tracks, "
      f"{len(usable)} with 3+ crops")
if len(usable) < 3:
    print("  too few tracks to measure")
    raise SystemExit(0)


def embed(crops):
    with torch.no_grad():
        out = enc(**eproc(images=crops, return_tensors="pt"))
    v = out.last_hidden_state[:, 0]
    return torch.nn.functional.normalize(v, dim=-1).numpy()


vecs = {k: embed(v) for k, v in usable.items()}
intra = [float(V[a] @ V[b]) for V in vecs.values()
         for a, b in itertools.combinations(range(len(V)), 2)]
inter = [float(a @ b) for k1, k2 in itertools.combinations(vecs, 2)
         for a in vecs[k1] for b in vecs[k2]]
intra, inter = np.array(intra), np.array(inter)
print(f"  same vehicle      : n={len(intra):>5}  mean {intra.mean():.3f}  "
      f"p05 {np.percentile(intra, 5):.3f}")
print(f"  different vehicles: n={len(inter):>5}  mean {inter.mean():.3f}  "
      f"p95 {np.percentile(inter, 95):.3f}")
print(f"  separation (intra p05 - inter p95): "
      f"{np.percentile(intra,5) - np.percentile(inter,95):+.3f}")
best = max((( (intra >= t).mean() + (inter < t).mean() ) / 2, t)
            for t in np.arange(0.3, 1.0, 0.01))
print(f"  best balanced accuracy: {best[0]:.3f} at threshold {best[1]:.2f}")
