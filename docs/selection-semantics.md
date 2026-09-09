# Candidate selection semantics v1

`generic_cog_build_preview` (`application/cog_preview.py`) is now the only
recommendation engine — the specialized Darius-versus-Garen exhaustive engine
this document originally also described was removed in P1-066 (see
`TASKS.md`). Some of what follows was true for that removed engine but is
**not implemented** in the generic engine that remains; those gaps are called
out explicitly rather than silently dropped, per this project's own rule that
a model's limits must be stated, not hidden.

## Evaluation order

1. Enumerate every legal ordered three-item path exhaustively (P1-067; no
   pruning between cores — see `TASKS.md`), rejecting hard legality
   violations (budget, boots limit, `purchase_exclusive` conflicts) and
   structurally unscoreable ones
   (`item_combat.duplicate_group_blockers` — a repeated `shared_cooldown` or
   `same_passive` group with no interaction handler to avoid double-counting
   it) as they are found.
2. Compute the weighted objective vector for each surviving path.
3. For each branch independently, apply that branch's own admissibility gate.
4. Rank the gated pool with the branch's priority metrics and deterministic
   tie-breakers.

**Not implemented in the generic engine:** a per-target kill-threshold gate
(`KILL_THRESHOLD_MET_3S`, "is the target dead within N seconds") and
epsilon-Pareto dominance filtering. Both existed only in the removed
specialized engine. The generic engine's gates are readiness booleans
(`ALL_CORE_ENGAGE_READY`, `ALL_CORE_CHASSIS_READY`, `ALL_CORE_ITEM_PASSIVES_READY`)
and, for `DEFENSE`, a relative damage-loss floor — never a raw-damage-versus-
target-HP kill check.

## Branch gates and ranking

- `DEFAULT`: gated on `ALL_CORE_CHASSIS_READY` (engagement uptime and a
  minimum mixed-effective-health ratio against the no-item baseline at every
  core) and `ALL_CORE_ITEM_PASSIVES_READY`. **The gate is not a weighted
  combination of damage and defense: candidates that pass are still ranked by
  `DAMAGE_TOTAL_8S`**, then `MIXED_EFFECTIVE_HEALTH` as a tie-break (P1-068;
  this branch previously ranked by survival metrics instead, which was a
  divergence from this same rule — fixed, not a design change). If no
  candidate meets the chassis gate at all, every legal candidate becomes
  eligible instead of none.
- `OFFENSE`: the unconstrained damage branch — no chassis or defense gate,
  ranked by `DAMAGE_TOTAL_8S` then `ENGAGE_COMBAT_UPTIME_FRACTION`.
- `DEFENSE`: gated on the same chassis readiness as `DEFAULT`, plus
  `defense_candidate_is_feasible` — `DAMAGE_TOTAL_8S` within a configured
  relative loss fraction of the best damage among chassis-ready candidates.
  Candidates that pass are ranked by `ACTOR_SURVIVAL_MS_8S`, then
  `MIXED_EFFECTIVE_HEALTH`, `LANE_RECOVERED_HP_30S`, `ACTOR_END_HP_8S`. This
  keeps "can the champion start and survive the fight?" (the gate) separate
  from "how much damage is dealt after contact?" for `DEFAULT`/`OFFENSE`,
  while `DEFENSE` inverts which side is the gate and which is the ranking.
  Each of its two gates falls back independently instead of dropping the
  branch outright, mirroring `DEFAULT`'s own chassis fallback (P1-070): if no
  candidate meets the chassis gate at all, every legal candidate is ranked
  instead (`DEFENSE_FALLBACK_NO_FULL_CHASSIS`); if chassis-ready candidates
  exist but none meets the damage-loss floor, every chassis-ready candidate is
  ranked without that floor (`DEFENSE_FALLBACK_NO_DAMAGE_FLOOR_MET`). `DEFENSE`
  is therefore always present in the response, same as `DEFAULT`/`OFFENSE`.

Final ties are resolved by `CORE_COMPLETION_GOLD_WEIGHTED` (build-progression-
weighted gold), then raw total gold, then the ordered item-id tuple itself
(this project has no shorter/longer builds to break ties on — every branch is
a fixed three-item path).

Whether a branch's gate is enabled is not per-champion policy data in the
generic engine; the same gates apply uniformly to every actor, matching the
"no matchup- or champion-specific dispatch" rule established in P1-066.

## Build progression and conditional readiness

An ordered build is evaluated on an explicit core-completion timeline. Prefix
metrics are weighted by the amount of scenario time spent at each completed
core, rather than averaged as three interchangeable snapshots. Long-lived
stacking effects consume fixture-declared proc opportunities after their actual
purchase time. Consequently, moving Heartsteel from first to third core cannot
retain stacks from time before it was owned.

Conditional passives remain distinct from an item's unconditional stats.
Warmog's Armor still grants health while Warmog's Heart is dormant. **The
generic engine tracks this as a single boolean** (`warmog_heart_ready`, fed
into `ALL_CORE_ITEM_PASSIVES_READY` and the lane-sustain window's regen bonus)
rather than a continuous dormant-passive duration; there is no dormant-time
tie-break to minimize. A per-item continuous readiness cost, if wanted, is not
implemented.

The progression timestamps and opportunity cadence are scenario inputs. Until
validated against observations, they must remain visible release blockers.

## Lane sustain and engagement

Lane sustain is evaluated in a separate deterministic recovery window. It uses
base health regeneration, item base-regeneration modifiers, life steal from an
explicit number of minion attacks, and conditional out-of-combat healing. It is
not added to duel damage or EHP.

Engagement uses a straight-line pursuit fixture with initial distance, attack
range, movement-speed soft caps, target retreat speed, item slows, item movement
actives, momentum, and forward dashes. It returns distance closed, contact
state, contact time, and the remaining combat-window fraction. Summoner spells
are either modeled explicitly or excluded with a blocker; their effects are
never silently assumed.

A short, cooldown-bound item active's contribution to the pursuit window is
credited as `uncorrelated` by default: the share of wall-clock time the
active is actually up (`duration / cooldown`), not merely how much of the
window its duration alone would cover if it were assumed to be saved for this
exact fight (`per_engagement`). Crediting by duration alone let a long-cooldown
item's incidental movement grant compete as if it were always available and
measurably win item slots on that side effect alone (P1-070; see `TASKS.md`).
`item_combat.ACTIVE_DUTY_POLICIES` documents all three named readings, since
none is recorded in patch data.

See [Branch gates and ranking](#branch-gates-and-ranking) above for exactly
which readiness booleans gate each branch and which metric ranks it.

## Mixed-damage durability

`core/combat.py`'s effective-health formulas (see `docs/combat-math.md`) keep
physical, magical, true, and mixed EHP as separate functions, and the mixed
one is not a weighted arithmetic mean of physical and magical EHP:

```text
mixed multiplier = physical_share * physical_multiplier
                 + magical_share * magical_multiplier
                 + true_share

mixed EHP        = survivable_health_pool / mixed_multiplier
```

**The generic engine's branch metrics only expose the single blended result**
as `MIXED_EFFECTIVE_HEALTH` (`_beam_metrics` in `cog_preview.py`) — it does
not carry `PHYSICAL_EHP`/`MAGICAL_EHP` as separate ranked dimensions the way
the removed specialized engine did. Conditional shields, healing, and damage-
reduction effects still require simulation or an explicitly defined time-
window contribution to enter that blend.

## CC-adjusted uptime

The first scenario must contain at least one deterministic CC event. Its event
declares when it occurs, its base duration, and which action channels it blocks.
The referenced mechanic record separately declares whether tenacity, Cleanse,
QSS, and immunity interact with it.

An `UNVERIFIED` mechanic may be loaded for schema work, but it cannot produce a
release-eligible recommendation. The evaluator must surface an unknown result or
fail the release gate instead of silently applying a remembered rule.

The timeline layer exposes uptime per action channel rather than folding every
channel into an ungrounded scalar. A champion objective profile may later select
or combine those verified channel values; that policy is not inferred inside
the CC engine.

## Semantic invariants outside JSON Schema

- Incoming damage shares sum to exactly 1 within the configured tolerance.
- Every CC event occurs within the encounter duration.
- Branch IDs are exactly `DEFAULT`, `OFFENSE`, and `DEFENSE`, without duplicates.
- Reproduction snapshots match the locked patch and recipe.
- A verified scenario references verified mechanic records for every CC event.
