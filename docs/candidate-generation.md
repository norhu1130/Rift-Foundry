# Ordered complete-item candidate generation

This describes `items/candidates.py` and `items/evaluation.py`, used by the
non-release `on_hit_preview.py` prototype pipeline. The actual recommendation
engine (`application/cog_preview.py`) generates and legality-checks candidates
with its own, separate implementation; it reaches the same practical outcome
for `same_passive`/`shared_cooldown` duplicates (excluded, not scored) but by
excluding them at generation time via
`item_combat.duplicate_group_blockers` rather than deferring to an `UNKNOWN`
portfolio result at evaluation time — see `docs/selection-semantics.md`.

Version 1 enumerates permutations of the curated complete-item pool for one,
two, and three complete-item milestones. Item order is part of candidate
identity. Each candidate preserves every item's component recipe, but component
purchase timing is not simulated in v1.

Hard rejection rules are absence from the locked-patch item ID set, patch
mismatch, duplicate purchase-limit group,
budget, inventory slots, positive mana on a manaless champion, and critical
strike chance above the configured cap. Every rejection retains a reason and
detail for audit.

The three group types deliberately have different behavior:

- duplicate `purchase_limit` is illegal and removes the candidate;
- duplicate `same_passive` remains legal but is annotated so evaluation does
  not count the passive twice;
- duplicate `shared_cooldown` remains legal but is annotated so simulation can
  share its trigger state.

The generator does not pretend that same-passive and shared-cooldown groups are
purchase restrictions. Their numeric behavior belongs to later evaluation.

The portfolio evaluator refuses to produce stats or effect values when either
annotation is duplicated and no explicit interaction handler exists. Likewise,
a named temporal exception without an implemented handler makes the portfolio
`UNKNOWN`. Legal-to-purchase therefore does not imply safe-to-score.
