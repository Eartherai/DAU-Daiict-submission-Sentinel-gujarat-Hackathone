# ADR-007: Hash-chained manifests and BSA s.63 preparation; no blockchain
**Status:** accepted **Date:** 2026-09-01

## Context
Section 63 of the Bharatiya Sakshya Adhiniyam 2023 (in force 1 July 2024,
replacing IEA s.65B) requires a certificate identifying the electronic record,
describing how it was produced, giving device particulars, **disclosing the hash
value**, and signed by the person in charge **and** an expert.

## Options
1. Nothing beyond a file export.
2. **SHA-256 + hash-chained audit + prepared s.63 certificate.**
3. Blockchain / distributed ledger.
4. Third-party notarisation.

## Evaluation
A hash chain plus a signature provides tamper-evidence. Blockchain's
distributed-consensus property solves a problem we do not have — there is one
custodian — and signals inexperience to a technical jury. No VMS vendor
generates the s.63 certificate, and one of the challenge's knowledge partners is
the National Forensic Sciences University.

## Decision
Option 2. The certificate is generated with `status: DRAFT_PENDING_SIGNATURE`
and **empty signature blocks**.

## Trade-offs accepted
We cannot claim admissibility — that is the court's determination. The system
*prepares*; authorised humans certify. No UI string may say otherwise.

## Revisit when
A court or SCRB publishes a specific format requirement.
