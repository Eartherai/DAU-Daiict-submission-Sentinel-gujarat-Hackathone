# Ground-truth-lite

This is a deliberately small, manual annotation format for OCR evaluation.
It records only observations a reviewer has actually verified; blank or
uncertain text must remain blank. It is not a generated-label or synthetic
truth source.

`schema.json` is a JSON Schema draft 2020-12 document. Copy
`template.jsonl` and add one object per verified crop (one JSON object per
line). `image` is relative to the repository root or to the manifest's
directory. `plate` is optional: omit it when the crop is unreadable. A
`verified: false` row is useful for documenting a reviewed but unusable crop
and is excluded from scored accuracy.

Required review provenance is `reviewer`, `verified`, and `image`. Do not infer
the plate from a model prediction when completing this file.
