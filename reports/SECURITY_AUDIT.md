# Security audit

**Result: strong application-layer controls verified; host/database compromise
out of scope.**

## Verified controls

`var/reports/security_scorecard.json` records adversarial checks for missing
authentication, role separation, purpose binding, jurisdiction, injection,
path traversal, credential leakage, evidence access, and audit integrity.
`docs/SECURITY.md` identifies the enforcement files and tests.

The API uses bound SQLAlchemy parameters, bounded queries and exports,
credential redaction, CSP/security headers, request IDs, role permissions,
district scope, purpose headers, hash-chained evidence/audit records, and
fail-closed edge bundle checks.

## Residual risks

The application cannot defend against a compromised host, direct database-file
access, physical camera tampering, or a stolen infrastructure secret outside
the token revocation path. PostgreSQL deployment hardening, secret rotation,
network policy, backups, and key custody remain deployment responsibilities.

## Reproduction

```bash
make test-security
make security-scorecard
make secrets
```
