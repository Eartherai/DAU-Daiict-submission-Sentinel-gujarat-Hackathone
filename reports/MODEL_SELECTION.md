# Model selection

The selection evidence currently available is the checked-in
`var/logs/benchmark/plate_detect_ocr.json`, produced on the local synthetic
corpus (`DEV_CPU`, arm64, no CUDA GPU). It measured `anpr-onnx-cpu@1.0.0` at
0.8333 exact OCR match, 0.525 character accuracy, 61.69 ms p50 and 92.71 ms
p95; `anpr-onnx-fastalpr-default@0.0.0` produced no valid reads on that run.

These are regression comparisons on the named corpus, not field accuracy.
The first model remains the conservative default because it produced valid
format-checked reads and is MIT licensed. `C-033` was explicitly declined in
that run rather than being treated as a successful zero. Re-run the benchmark
before changing this decision; no claim is made for a model that was not
actually loaded and measured.
