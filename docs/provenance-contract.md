# Recommendation provenance contract

Every recommendation number and explanation carries one evidence label. The
label is enforced structurally rather than added as presentation text.

- `MEASURED`: a finite observed value plus one or more measurement references.
- `CALCULATED`: a finite value plus a versioned formula reference and its input
  references.
- `UNVERIFIED`: no numeric value and at least one explicit blocker.

Recommendation provenance also records the game patch, patch lock, scenario,
candidate, ordered item IDs, raw source files, and every mechanic dependency.
Release eligibility is derived from those records and cannot be supplied by a
caller. Any unverified claim or non-verified mechanic makes the document
non-release-eligible.

The v1 pipeline must not use an `UNVERIFIED` numeric record as a placeholder
score. It can return that record only with `INSUFFICIENT_EVIDENCE` so the missing
evidence remains visible without affecting Pareto or branch selection.
