# OCR evaluation

## Evidence

The runnable evaluator is `tools/benchmark_ocr.py` (`make benchmark-ocr`). It
scores only manually verified rows from
`evaluation/ground_truth_lite`; it does not turn model output into truth.
Scores are exact text, separator-normalised text, positional character
accuracy, and measured OCR latency (p50/p95).

At the time of this report the checked-in lite manifest is a template with one
explicitly unreadable row and `var/evaluation/crops` is not present. Therefore
the current result is **UNAVAILABLE**, not zero accuracy. Run the command after
adding reviewer-verified crops to obtain a measured JSON report under
`var/reports/ocr_evaluation.json`.

## Interpretation

Unverified, missing, empty, or unreadable rows are counted separately and are
never silently scored as misses. A single strong OCR read remains a
`REQUIRES_VERIFICATION` lead; temporal consensus reuses `PlateVoter` and does
not fabricate a plate.
