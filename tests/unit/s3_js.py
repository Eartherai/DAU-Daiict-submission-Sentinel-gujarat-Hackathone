"""Run named pieces of ui/app.js under Node, without a browser.

app.js is one ES module that touches the DOM at load, so it cannot be imported
whole. The pure helpers — time formatting, the markdown tokenizer — are lifted
out by name and evaluated on their own, which tests the code that actually
ships rather than a copy of it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "ui" / "app.js"


def _block_end(src: str, start: int) -> int:
    """Index just past the statement that begins at `start`.

    Brace-matching with string and comment awareness is enough for the plain
    functions and const declarations these tests lift.
    """
    depth = 0
    i = start
    in_str: str | None = None
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif src.startswith("//", i):
            i = src.index("\n", i)
            continue
        elif src.startswith("/*", i):
            i = src.index("*/", i) + 2
            continue
        elif ch in "\"'`":
            in_str = ch
        elif ch == "/" and depth >= 0 and src[i - 1] in "(,=:[!&|?{};\n " \
                and not src.startswith("/*", i) and not src.startswith("//", i):
            # A regex literal: skip to its closing slash, honouring classes.
            j, cls = i + 1, False
            while j < len(src):
                c = src[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    cls = True
                elif c == "]":
                    cls = False
                elif c == "/" and not cls:
                    break
                elif c == "\n":
                    break
                j += 1
            if j < len(src) and src[j] == "/":
                i = j + 1
                continue
        elif ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
            if depth == 0 and ch == "}" and src[start:].startswith(("function", "async function")):
                return i + 1
        elif ch == ";" and depth == 0:
            return i + 1
        i += 1
    raise ValueError("unterminated block")


def lift(*names: str) -> str:
    src = APP_JS.read_text(encoding="utf-8")
    out = []
    for name in names:
        for head in (f"function {name}(", f"async function {name}(",
                     f"const {name} = "):
            k = src.find("\n" + head)
            if k >= 0:
                k += 1
                out.append(src[k:_block_end(src, k)])
                break
        else:
            raise AssertionError(f"{name} not found in ui/app.js")
    return "\n".join(out)


def run_node(code: str, *, tz: str = "UTC") -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = {**os.environ, "TZ": tz}
    p = subprocess.run([node, "--input-type=module", "-e", code],
                       capture_output=True, text=True, env=env, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])
