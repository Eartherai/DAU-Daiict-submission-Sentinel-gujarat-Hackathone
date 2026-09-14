"""Deterministic, sortable identifiers.

Event ids are ULID-like: 48-bit millisecond timestamp + 80 bits of entropy,
Crockford base32. Sortable by creation time, which makes ordered replay and
late-arrival detection cheap without a separate sequence column.
"""
from __future__ import annotations

import os
import time

_A = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)


def _b32(n: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_A[n & 0x1F])
        n >>= 5
    return "".join(reversed(out))


def new_id(prefix: str = "") -> str:
    ts = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    core = _b32(ts, 10) + _b32(rand, 16)
    return f"{prefix}{core}" if prefix else core


def event_id() -> str:
    return new_id("EV")


def evidence_id() -> str:
    return new_id("EZ")


def observation_id() -> str:
    return new_id("OB")
