"""Required deliverables cannot silently disappear from a rebuilt pack."""
import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_submission_pack", Path(__file__).resolve().parents[2] / "tools/demo/build_submission_pack.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


@pytest.mark.parametrize("missing", [None, "02_HLD_diagrams.pdf",
                                    "06_designated_vehicle_trace_report.html"])
def test_pack_requires_diagrams_and_trace_and_removes_internal_checklist(tmp_path, monkeypatch, capsys, missing):
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    monkeypatch.setattr(pack, "_probe", lambda _: "")
    monkeypatch.setattr(sys, "argv", ["build_submission_pack.py"])
    for name, rel, required in pack.ITEMS:
        if name != missing and required:
            source = tmp_path / rel
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("test artifact")
    dest = tmp_path / "var/demo/SUBMIT"
    dest.mkdir(parents=True)
    (dest / "00_CHECKLIST.md").write_text("stale internal checklist")
    internal = tmp_path / "docs/SUBMISSION_CHECKLIST.md"
    internal.write_text("internal checklist")
    assert pack.main() == (1 if missing else 0)
    output = capsys.readouterr().out
    if missing:
        assert "REFUSED" in output and missing in output
    else:
        assert (dest / "02_HLD_diagrams.pdf").is_file()
        assert (dest / "06_designated_vehicle_trace_report.html").is_file()
    assert not (dest / "00_CHECKLIST.md").exists()
    assert internal.read_text() == "internal checklist"
