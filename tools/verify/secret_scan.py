#!/usr/bin/env python3
"""Secret scan over tracked files and full git history.

Pattern-based and dependency-free on purpose, so the gate always runs — including
on a machine with no network and no gitleaks. It is a floor, not a replacement
for a proper scanner in CI.

Scans history as well as the working tree, because a credential removed in a
later commit is still disclosed by the repository.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PATTERNS: dict[str, re.Pattern[str]] = {
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "generic_bearer": re.compile(r"[Bb]earer\s+[A-Za-z0-9\-._~+/]{24,}"),
    "password_assign": re.compile(
        r"(?i)\b(password|passwd|api_key|secret)\s*=\s*['\"][^'\"]{8,}"),
}

#: Lines that define or document a pattern rather than containing a credential.
#: Without this the scanner reports itself.
ALLOW = re.compile(r"(PATTERNS:|re\.compile|# noqa: secret|EXAMPLE_ONLY|ALLOW =)")

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".mp4", ".onnx", ".safetensors", ".pdf"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    return [ROOT / p for p in out.stdout.split() if p]


def scan_text(text: str, where: str) -> list[str]:
    hits: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if ALLOW.search(line):
            continue
        for name, pat in PATTERNS.items():
            if pat.search(line):
                hits.append(f"{where}:{i}: {name}")
    return hits


def main() -> int:
    findings: list[str] = []
    files = tracked_files()

    for f in files:
        if not f.is_file() or f.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            findings += scan_text(f.read_text(errors="ignore"),
                                  str(f.relative_to(ROOT)))
        except OSError:
            continue

    hist = subprocess.run(["git", "log", "--all", "-p"], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    for name, pat in PATTERNS.items():
        n = len(pat.findall(hist.stdout))
        if n:
            findings.append(f"git-history: {name} appears {n}x")

    if findings:
        print("SECRET SCAN: FAIL")
        for f in findings[:40]:
            print(f"  {f}")
        return 1
    print(f"SECRET SCAN: PASS ({len(files)} tracked files + full history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
