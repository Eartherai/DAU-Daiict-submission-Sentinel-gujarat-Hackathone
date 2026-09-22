"""The Model 1 registry portal has an onboarding surface.

Model 1 is the mandatory model and its named deliverables include a "bulk and
manual camera-onboarding demonstration" and a "working registry portal". Until
this was added the three /registry/ endpoints existed and the operator
workspace never called any of them — onboarding could only be shown with a
shell, and an assessor cannot be asked to take curl on trust.

These assert against the shipped UI source rather than a browser, in the idiom
the rest of the UI tests already use. The behaviour was additionally driven in
a real browser against a live server: dry run wrote nothing, a duplicate was
refused naming the row, an amend landed, and a two-row CSV whose second row was
bad left the first row unwritten.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui"
APP = (UI / "app.js").read_text(encoding="utf-8")
INDEX = (UI / "index.html").read_text(encoding="utf-8")


def test_the_workspace_reaches_all_three_registry_endpoints() -> None:
    for path in ("/registry/cameras/import",
                 "/registry/cameras/import.csv",
                 "/registry/cameras/export.csv"):
        assert path in APP, f"the UI never calls {path}"


def test_both_onboarding_methods_are_offered() -> None:
    """The deliverable names bulk AND manual; one of the two is not enough."""
    assert 'data-onboard="manual"' in INDEX
    assert 'data-onboard="bulk"' in INDEX
    assert 'id="ob-camera-id"' in INDEX, "no manual entry field for the id"
    assert 'id="ob-csv"' in INDEX, "no bulk paste area"


def test_only_the_camera_id_is_marked_required() -> None:
    """A registry holds what is known and reports what is not.

    Marking department or coordinates required in the form would contradict the
    gap report, which exists precisely to name the fields nobody supplied.
    """
    required = re.findall(r'<input id="(ob-[a-z-]+)"[^>]*\brequired\b', INDEX)
    assert required == ["ob-camera-id"], (
        f"unexpected required fields: {required}")


def test_dry_run_is_sent_where_the_json_endpoint_reads_it() -> None:
    """dry_run is a field on ImportRequest, not a query parameter.

    Sent in the query string it is silently ignored and the row is written, so
    a "Validate only" button would onboard for real. That is worse than having
    no dry run at all, because the operator is told nothing happened.
    """
    call = APP[APP.index("async function obSubmitManual"):
               APP.index("$(\"#onboard-manual\")")]
    assert "dry_run: !!dry" in call, "dry_run is not in the JSON request body"
    assert "import?dry_run" not in call and "${q}" not in call, (
        "dry_run is being passed as a query parameter to the JSON endpoint, "
        "where it is ignored")


def test_the_csv_endpoint_takes_dry_run_as_a_query_parameter() -> None:
    """The two endpoints genuinely differ; the UI must match each."""
    call = APP[APP.index("async function obSubmitBulk"):
               APP.index("$(\"#btn-ob-bulk-dry\")")]
    assert 'params.set("dry_run", "true")' in call


def test_the_export_is_fetched_with_credentials() -> None:
    """A plain <a href> download arrives unauthenticated and returns 401.

    The ANPR report download already shipped that bug once.
    """
    block = APP[APP.index('$("#btn-ob-export")'):]
    assert "authHeaders()" in block, (
        "the export is not sent with an Authorization header")


def test_the_refusal_is_shown_rather_than_flattened() -> None:
    """The server names the offending row and the remedy; keep both.

    "Import failed" is not actionable. "row 2: MC-0002 is already onboarded.
    Re-send with update_existing=true" is.
    """
    assert "err.code" in APP and "err.message" in APP
    block = APP[APP.index("function obReport"):APP.index("function obShowPane")]
    assert "created" in block and "updated" in block, (
        "the success report does not read the fields the API actually returns")


def test_amending_an_existing_row_must_be_asked_for() -> None:
    """Re-uploading a stale spreadsheet must not silently overwrite curation."""
    assert 'id="ob-update-existing"' in INDEX
    assert "update_existing" in APP
