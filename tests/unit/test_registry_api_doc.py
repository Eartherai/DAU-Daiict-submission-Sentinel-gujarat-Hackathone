"""The registry API documentation is generated, not written.

A named Model 1 deliverable. Hand-written API documentation drifts the first
time a field is added and nobody notices until an integrator does; generating
it from the service's own schema means the worst case is that it is terse, not
that it is wrong.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reports"))

import registry_api_doc as doc


def _spec() -> dict:
    return {
        "paths": {
            "/registry/cameras/import": {
                "post": {"summary": "Bulk camera onboarding (JSON)"}},
            "/registry/cameras/export.csv": {
                "get": {"summary": "Export the registry",
                        "parameters": [{"name": "department", "in": "query",
                                        "schema": {"type": "string"}}]}},
            "/gis/gaps": {"get": {"summary": "Registry gap analysis"}},
            "/alerts": {"get": {"summary": "not a registry endpoint"}},
        },
        "components": {"schemas": {"CameraIn": {
            "required": ["camera_id"],
            "properties": {
                "camera_id": {"type": "string"},
                "lat": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "vms": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            }}}},
    }


def test_it_documents_the_registry_surface():
    text = doc.render(_spec(), "http://x", {})
    assert "POST /registry/cameras/import" in text
    assert "GET /gis/gaps" in text


def test_it_leaves_out_endpoints_that_are_not_the_registry():
    """This report is for the integrator onboarding cameras."""
    text = doc.render(_spec(), "http://x", {})
    assert "not a registry endpoint" not in text


def test_required_fields_are_marked_and_optional_ones_are_not():
    text = doc.render(_spec(), "http://x", {})
    assert "| `camera_id` | string | **yes** |" in text
    assert "| `vms` | string | no |" in text


def test_a_nullable_field_documents_its_real_type_not_null():
    """`anyOf: [number, null]` is a number an integrator may omit."""
    fields = dict((f, k) for f, k, _ in doc._schema_fields(_spec(), "CameraIn"))
    assert fields["lat"] == "number"
    assert fields["vms"] == "string"


def test_it_states_the_contract_an_integrator_relies_on():
    text = doc.render(_spec(), "http://x", {})
    flat = " ".join(text.split())
    assert "applies wholly or not at all" in flat
    assert "dry_run" in flat
    assert "update_existing" in flat
    assert "round-trips into import" in flat.lower() or "Export round-trips" in text


def test_worked_examples_are_included_verbatim():
    text = doc.render(_spec(), "http://x", {"Onboard": "POST /x\n{}"})
    assert "### Onboard" in text and "POST /x" in text
