"""What each government system can feed, and which alerts CCTV can actually raise.

The challenge names five systems — VAHAN, SARATHI, eGujCop (CCTNS), AFIS and
NAFIS — and six alert categories: arrested persons, stolen vehicles, wanted
criminals, missing persons, unidentified bodies, and fingerprint matches.

Listing five integrations and six alert types is easy. The useful work is saying
which of them a **camera** can trigger, because they are not equivalent and
promising all six would be a claim this system cannot keep:

* **Vehicle-keyed** alerts are actionable from ANPR today. A stolen vehicle, or
  a vehicle associated with a wanted person, is matched on a registration mark
  the pipeline already reads.
* **Face-keyed** alerts — wanted criminals, missing persons, unidentified bodies
  — require face recognition. This system **does not do face recognition**, as a
  deliberate decision recorded in the architecture, not a missing feature. The
  adapters carry those records so a control room can hold and search them; the
  cameras do not raise alerts from them.
* **Fingerprint-keyed** alerts — AFIS and NAFIS — cannot be driven by CCTV at
  all. No camera on this or any estate captures a fingerprint. These sources are
  integration-ready for *enrichment*: given a person already identified by other
  means, the interface returns what those systems hold. A CCTV platform claiming
  fingerprint alerts would be claiming something physically impossible.

Every adapter refuses to fetch until it is given a real endpoint and
authorisation. `requires` names exactly what is missing, so an integration
conversation with a department starts from a list rather than a demand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Keyed(StrEnum):
    """What a record is matched on — and therefore what can raise it."""

    VEHICLE = "VEHICLE"          # a registration mark; CCTV can match this
    FACE = "FACE"                # a face; this system does not do face recognition
    FINGERPRINT = "FINGERPRINT"  # no camera captures one
    PERSON_RECORD = "PERSON_RECORD"   # a record, not a biometric


#: Whether a camera can raise an alert from a record keyed this way.
CCTV_CAN_TRIGGER: dict[Keyed, bool] = {
    Keyed.VEHICLE: True,
    Keyed.FACE: False,
    Keyed.FINGERPRINT: False,
    Keyed.PERSON_RECORD: False,
}


@dataclass(frozen=True)
class AlertCategory:
    """One of the six categories, and what it actually needs to fire."""

    name: str
    keyed: Keyed
    note: str

    @property
    def cctv_actionable(self) -> bool:
        return CCTV_CAN_TRIGGER[self.keyed]


CATEGORIES: tuple[AlertCategory, ...] = (
    AlertCategory(
        "stolen_vehicle", Keyed.VEHICLE,
        "Matched on the registration mark read by ANPR. Actionable today, on "
        "cameras graded able to read a plate."),
    AlertCategory(
        "vehicle_of_interest", Keyed.VEHICLE,
        "A vehicle associated with a case or a wanted person. Same mechanism as "
        "a stolen vehicle; the difference is the authority behind the entry."),
    AlertCategory(
        "wanted_person", Keyed.FACE,
        "Requires face recognition, which this system deliberately does not "
        "perform. Held and searchable; not raised from a camera."),
    AlertCategory(
        "missing_person", Keyed.FACE,
        "As above. A missing-person record can be held and searched; a camera "
        "cannot raise it without face recognition."),
    AlertCategory(
        "unidentified_body", Keyed.PERSON_RECORD,
        "A record to be matched against missing-person reports by an "
        "investigator. Not a live camera trigger under any configuration."),
    AlertCategory(
        "fingerprint_match", Keyed.FINGERPRINT,
        "No camera captures a fingerprint. Available for enrichment of a person "
        "already identified by other means; never a CCTV alert."),
)


@dataclass(frozen=True)
class SourceContract:
    """What a government system provides, and what is needed to reach it."""

    name: str
    system: str
    provides: tuple[str, ...]
    keyed: Keyed
    record_fields: tuple[str, ...]
    requires: tuple[str, ...]
    refresh: str
    note: str = ""

    @property
    def cctv_actionable(self) -> bool:
        return CCTV_CAN_TRIGGER[self.keyed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "system": self.system,
            "provides": list(self.provides), "keyed_on": str(self.keyed),
            "cctv_actionable": self.cctv_actionable,
            "record_fields": list(self.record_fields),
            "requires": list(self.requires), "refresh": self.refresh,
            "note": self.note,
        }


CONTRACTS: tuple[SourceContract, ...] = (
    SourceContract(
        name="VAHAN", system="Ministry of Road Transport vehicle registry",
        provides=("stolen_vehicle", "vehicle_of_interest"),
        keyed=Keyed.VEHICLE,
        record_fields=("registration_mark", "make", "model", "colour",
                       "owner_district", "status", "reported_at"),
        requires=("authorised API endpoint", "service credentials",
                  "data-sharing approval", "purpose limitation agreement"),
        refresh="incremental pull on a schedule; a stolen-vehicle report is "
                "time-critical and a nightly batch is too slow",
        note="The one source that maps directly onto what these cameras can "
             "read. Registration marks are the only biometric-free identifier "
             "on the road."),
    SourceContract(
        name="SARATHI", system="Driving licence registry",
        provides=("licence_status",),
        keyed=Keyed.PERSON_RECORD,
        record_fields=("licence_number", "holder_name", "status", "district"),
        requires=("authorised API endpoint", "service credentials",
                  "purpose limitation agreement"),
        refresh="on demand, per query",
        note="Enrichment only. A licence is not observable from a camera; this "
             "answers a question about a person already identified."),
    SourceContract(
        name="eGujCop", system="Gujarat Police CCTNS",
        provides=("wanted_person", "missing_person", "vehicle_of_interest",
                  "arrested_person"),
        keyed=Keyed.VEHICLE,
        record_fields=("case_number", "registration_mark", "person_name",
                       "category", "district", "issuing_authority", "issued_at"),
        requires=("SCRB authorisation", "CCTNS interface specification",
                  "network path to the CCTNS environment",
                  "record-level access policy"),
        refresh="near-real-time push preferred; a wanted-person entry that "
                "arrives a day late is of little use",
        note="The richest source. Only its **vehicle-keyed** records can raise "
             "a camera alert here; person-keyed records are held and searched, "
             "because this system does not perform face recognition."),
    SourceContract(
        name="AFIS", system="State automated fingerprint identification",
        provides=("fingerprint_match",),
        keyed=Keyed.FINGERPRINT,
        record_fields=("person_id", "match_score", "case_number"),
        requires=("state FSL authorisation", "AFIS interface specification",
                  "biometric handling approval"),
        refresh="on demand, per query",
        note="Cannot be driven by CCTV. No camera captures a fingerprint."),
    SourceContract(
        name="NAFIS", system="National automated fingerprint identification",
        provides=("fingerprint_match",),
        keyed=Keyed.FINGERPRINT,
        record_fields=("person_id", "match_score", "nafis_reference"),
        requires=("NCRB authorisation", "NAFIS interface specification",
                  "biometric handling approval"),
        refresh="on demand, per query",
        note="As AFIS. Listed because the challenge names it, and excluded from "
             "camera alerting for the same physical reason."),
)

BY_NAME: dict[str, SourceContract] = {c.name: c for c in CONTRACTS}


class SourceUnavailable(RuntimeError):
    """Raised instead of returning invented records."""


@dataclass
class GovernmentSource:
    """An adapter that refuses to pretend.

    A source with no endpoint raises, naming what is missing. It never returns
    an empty list, because an empty list is indistinguishable from "the registry
    holds nothing" and would let a demonstration show a working integration
    where there is none.
    """

    contract: SourceContract
    endpoint: str | None = None
    credential_env: str | None = None
    _records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        import os

        return bool(self.endpoint and (
            not self.credential_env or os.environ.get(self.credential_env)))

    def fetch(self, since: datetime | None = None) -> list[dict[str, Any]]:
        if not self.configured:
            raise SourceUnavailable(
                f"{self.contract.name} is not connected. Required before it "
                f"can be: {', '.join(self.contract.requires)}. No record is "
                f"returned rather than an empty list, because an empty list "
                f"looks like a working integration over an empty registry.")
        raise SourceUnavailable(
            f"{self.contract.name} has an endpoint configured but no client "
            "implementation. The interface specification is required before "
            "one can be written.")

    def load_representative(self, records: list[dict[str, Any]]
                            ) -> list[dict[str, Any]]:
        """Accept records in this source's shape, for demonstration.

        Labelled `REPRESENTATIVE` at every point it is used. The challenge
        permits a representative watchlist; it does not permit calling one a
        government feed, and nothing here does.
        """
        missing = [r for r in records
                   if not set(self.contract.record_fields[:1]) <= set(r)]
        if missing:
            raise ValueError(
                f"{len(missing)} record(s) lack "
                f"{self.contract.record_fields[0]}, which {self.contract.name} "
                "keys on")
        self._records = [{**r, "provenance": "REPRESENTATIVE",
                          "source": self.contract.name} for r in records]
        return self._records


def readiness() -> dict[str, Any]:
    """A single honest statement of where integration stands."""
    return {
        "sources": [c.to_dict() for c in CONTRACTS],
        "categories": [
            {"name": c.name, "keyed_on": str(c.keyed),
             "cctv_actionable": c.cctv_actionable, "note": c.note}
            for c in CATEGORIES],
        "actionable_from_cctv": [c.name for c in CATEGORIES if c.cctv_actionable],
        "not_actionable_from_cctv": [c.name for c in CATEGORIES
                                     if not c.cctv_actionable],
        "connected": [],
        "note": (
            "No government system is connected in this deployment. Each adapter "
            "names what it needs. Of the six alert categories the challenge "
            "lists, two are actionable from a camera today; three require face "
            "recognition this system deliberately does not perform, and one "
            "requires a fingerprint no camera can capture."),
    }
