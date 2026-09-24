#!/usr/bin/env bash
# Fetch the Indian plate recogniser (Awiros-ANPR-OCR, Apache-2.0) into var/models/.
#
#   tools/models/fetch_indian_ocr.sh              # weights + dictionary + licence (~150 MB)
#   tools/models/fetch_indian_ocr.sh --parity     # also PaddleOCR's ppocr/ (~10 MB) for
#                                                 # tools/bench/ocr_compare.py --parity
#
# The pipeline runs the weights under PyTorch (src/saakshya/analytics/ocr_indian_net.py);
# PaddlePaddle is needed only for the parity check. Every file is checked against the
# SHA-256 it had when the port was verified, so a changed upstream file is refused
# rather than silently loaded.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/var/models/awiros-anpr-ocr"
BASE="https://huggingface.co/Awiros/anpr-ocr/resolve/main"
mkdir -p "$DEST"

fetch() {  # name sha256
  local f="$1" want="$2"
  if [ -f "$DEST/$f" ] && [ "$(shasum -a 256 "$DEST/$f" | cut -d' ' -f1)" = "$want" ]; then
    echo "  $f: present"; return
  fi
  curl -fL --retry 3 -o "$DEST/$f.part" "$BASE/$f"
  local got; got="$(shasum -a 256 "$DEST/$f.part" | cut -d' ' -f1)"
  if [ "$got" != "$want" ]; then
    rm -f "$DEST/$f.part"
    echo "  $f: SHA-256 $got, expected $want - refused" >&2; exit 1
  fi
  mv "$DEST/$f.part" "$DEST/$f"; echo "  $f: fetched and verified"
}

fetch model.safetensors f9f1264e0c115a239ca6d6700a74ceffab17168b75dafc6c169c232012c68e47
fetch en_dict.txt       0a94bb85eb456a04aae7ba2505fde280818649440e122922adcc5f3ab073dc72
fetch LICENSE           c09023910f2bb42a4063d6c09e3301d44773cd9dd0a21b6a3bf61ad60a16b895

if [ "${1:-}" = "--parity" ]; then
  P="$ROOT/var/models/PaddleOCR"
  if [ ! -d "$P/ppocr" ]; then
    git clone --depth 1 --filter=blob:none --sparse https://github.com/PaddlePaddle/PaddleOCR.git "$P"
    git -C "$P" sparse-checkout set ppocr
  fi
  echo "  PaddleOCR ppocr/ at $P (pip install paddlepaddle to run the parity check)"
fi
echo "Indian plate OCR ready: $DEST"
