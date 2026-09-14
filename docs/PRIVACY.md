# Privacy

This system reconstructs where a vehicle has been. In practice that often means
reconstructing where a person has been, and the design has to start from that
rather than discover it later.

Everything below is implemented. Where something is a design position rather
than working code, it says so.

---

## 1. What is collected

| Data | Purpose | Retention |
|---|---|---|
| Vehicle observations — plate, colour, type, bounding box, quality | Investigation | Deployment policy; the schema carries `retention_days` per camera |
| Frame and clip crops, when evidence is sealed | Evidence | Until the case concludes |
| Camera registry, health, capability | Operations | Indefinite; not personal data |
| Audit records — who searched, when, why | Accountability | Must outlive the investigation |

**No face is detected, stored, matched or searched.** There is no face pipeline
in this codebase and no field for one. This is a deliberate design decision, not
an unimplemented feature — see §5.

---

## 2. Purpose limitation, enforced

The strongest privacy control here is that a vehicle search cannot run without a
case identifier and a written purpose. Not "should not" — the request is refused
at the authorisation gate before any data is read, and both values are written
into a hash-chained audit log.

This directly addresses the most likely misuse of a system like this, which is
not an external attacker but a legitimate user with an illegitimate reason.

Consequences an oversight body can rely on:

- Every retrieval of a movement history has a stated purpose attached to it.
- The purpose cannot be added afterwards, and the log cannot be edited without
  detection.
- A case export contains the full audit trail for that case alongside the
  findings, so what was done and why is one document.

---

## 3. Data minimisation

- **Jurisdiction scope** — an officer sees their district. Statewide access is a
  separate role, held by supervisors.
- **Query floors** — an unfiltered scan of the estate is refused. Every search
  must name at least a plate, an attribute, a camera, a district or a time.
- **Result caps** — hard limits on every list endpoint.
- **Stream URLs withheld** — investigators never receive camera stream URLs;
  they get observations and evidence, not live video access.
- **Embeddings are optional** — appearance embeddings are computed only when the
  analytics tier calls for them, and the baseline embedding model was measured
  and rejected (see `docs/MODEL_BENCHMARK.md`), so the default path stores none.

---

## 4. Accuracy, and the harm of false confidence

An investigative system that overstates its certainty causes a specific harm:
the wrong person is stopped. Controls against that are treated as privacy
controls, not just quality ones.

- A plate read is an **identification**. An appearance or attribute match is a
  **candidate requiring verification**, and is labelled that way in the data
  model, the API and the interface. The two are never rendered alike.
- **Abstention is a first-class outcome.** A poor crop produces no colour rather
  than a guessed one.
- Scores are **ordering scores, not probabilities**, and every response that
  carries one says so. Calling an uncalibrated score a probability invites an
  officer to treat 0.8 as "80% likely", which it is not.
- **Coverage gaps are stated, never inferred.** "No camera observed this
  vehicle" is never presented as "the vehicle was not there". Every gap
  explanation in the product carries that distinction in words.
- **UNKNOWN capability stays UNKNOWN.** A camera with too little evidence is not
  graded, so an officer is never told a camera is reliable when nobody has
  checked.

---

## 5. Why there is no face recognition

Asked directly by anyone reviewing this: the challenge concerns vehicles, and
adding facial recognition would import a substantially different legal, ethical
and accuracy problem for no gain against the stated task.

Concretely:

- Vehicle registration marks are **registered identifiers** with an
  authoritative source. A face is a biometric with no equivalent registry and no
  equivalent recourse when it is wrong.
- Face recognition error rates on CCTV-grade imagery are far worse than the
  controlled benchmarks usually quoted, and the errors are not uniformly
  distributed across the population.
- India has no comprehensive data-protection framework in force for this use.
  Deploying biometric identification ahead of that framework is a choice, and
  this system does not make it.

If a deployment later requires it, that is a separate decision with a separate
authorisation, and it is not made easier by having quietly built the plumbing.

---

## 6. Watchlist provenance

Every watchlist entry records `source_system`. Entries created here are marked
`REPRESENTATIVE`, and that label travels into every alert and every API
response.

**No government watchlist is integrated.** VAHAN, SARATHI, eGujCop/CCTNS, AFIS
and NAFIS adapters exist as interfaces that raise `NotImplementedError` naming
the authorisation, endpoint and data-sharing agreement each would require. This
is stated in the API response body, not only in documentation, so a screenshot
cannot be mistaken for a live integration.

Watchlist amendments **supersede rather than mutate**: an alert raised last week
remains explicable in terms of what the list said last week.

Attribute-only watchlist matching is impossible by construction. "A white
hatchback" is not a vehicle of interest, and alerting on one would erode trust
in every genuine alert.

---

## 7. Individual rights

Design positions, honestly labelled as such — a real deployment must decide
these with legal advice, and the system is built so the answers are possible:

- **Access** — every retrieval of a person's vehicle history is in the audit
  log, filterable by target. A subject-access response is a query, not an
  investigation.
- **Rectification** — observations are immutable; a correction is a new record.
  Watchlist entries are amended by supersession, keeping history.
- **Erasure** — not implemented. Deleting an observation would break the
  evidence hash chain, so erasure needs a designed mechanism (tombstones with
  chain continuity), not an ad-hoc delete. Stated rather than pretended.
- **Retention** — `retention_days` exists per camera in the registry. No
  automatic enforcement job is implemented; that is a deployment task and is
  listed as outstanding rather than claimed.

---

## 8. Evidence and BSA s.63

Evidence records are hash-chained and carry a **draft** certificate under
s.63 of the Bharatiya Sakshya Adhiniyam, with both signature blocks empty and
status `DRAFT_PENDING_SIGNATURE`.

The system does not and cannot make evidence admissible. Admissibility is a
judicial determination. What it does is prepare the material and the technical
attestations a person in charge and an expert would need in order to sign — and
it never uses the phrase "legally admissible", which a test asserts appears
nowhere in any export.
