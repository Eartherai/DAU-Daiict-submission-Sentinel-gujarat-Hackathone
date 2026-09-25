#!/usr/bin/env bash
# Fetch the Indian plate recogniser (Awiros-ANPR-OCR, Apache-2.0) into var/models/.
#
#   tools/models/fetch_indian_ocr.sh              # weights + dictionary + licence (~150 MB)
#   tools/models/fetch_indian_ocr.sh --parity     # also PaddleOCR's ppocr/ (~10 MB) for
#                                                 # tools/bench/ocr_compare.py --parity
#
# The pipeline runs the weights under PyTorch (src/saakshya/analytics/ocr_indian_net.py);
# PaddlePaddle is needed only for the parity check. The weights, dictionary and licence
# are each checked against the SHA-256 they had when the port was verified, and ppocr/
# is checked out at the PaddleOCR commit it was verified against, so a changed upstream
# file is refused rather than silently loaded - or, for ppocr/, imported and run.
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
  # The commit the PyTorch port was checked against. The parity check imports and runs
  # ppocr/ from here, so it is this commit or nothing - never the default branch's HEAD.
  PPOCR_COMMIT=dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf
  if [ ! -d "$P/.git" ]; then
    git init -q "$P"
    git -C "$P" remote add origin https://github.com/PaddlePaddle/PaddleOCR.git
    git -C "$P" sparse-checkout set ppocr
  fi
  if [ "$(git -C "$P" rev-parse -q --verify HEAD || true)" != "$PPOCR_COMMIT" ]; then
    git -C "$P" fetch -q --depth 1 --filter=blob:none origin "$PPOCR_COMMIT"
    git -C "$P" -c advice.detachedHead=false checkout -q "$PPOCR_COMMIT"
  fi
  got="$(git -C "$P" rev-parse HEAD)"
  if [ "$got" != "$PPOCR_COMMIT" ]; then
    echo "  PaddleOCR at $got, expected $PPOCR_COMMIT - refused" >&2; exit 1
  fi
  if [ -n "$(git -C "$P" status --porcelain --untracked-files=no -- ppocr)" ]; then
    echo "  PaddleOCR ppocr/ differs from $PPOCR_COMMIT - refused" >&2; exit 1
  fi
  echo "  PaddleOCR ppocr/ at $P, commit $PPOCR_COMMIT (pip install paddlepaddle to run the parity check)"
fi
echo "Indian plate OCR ready: $DEST"
