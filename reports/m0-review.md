# P0-054 M0 cost and design review

- Review date: 2026-09-08
- Locked patch: `16.17.1`, 538 files under `patch.lock.json`
- Decision: **proceed to Phase 1 with the current schemas; do not iterate Phase 0**
- Gate status: M0 remains open on client measurement, not on engineering

## What the milestone produced

| Metric | Result |
|---|---:|
| Runtime source files | 233 |
| Runtime source lines | 50,458 |
| Automated tests | 801 |
| Lint findings | 0 |
| Schemas | 8 |
| Curated item-effect documents | 201 |
| Effect programs inside them | 311 |
| Items with an unimplemented core effect | 0 |
| Champion Cogs | 173 |
| Cogs with a modeled rotation | 109 |
| Cogs still scaffolded | 64 |
| Cogs modeling area abilities | 4 |
| Curated mechanic facts | 4 |

## Unverified facts

Every curated artifact is honest about its own status rather than promoted:

- All 201 item-effect documents are `CURATED_UNVERIFIED`.
- All 4 mechanic facts are `UNVERIFIED`; none is recorded as `false` for want of
  a measurement.
- All 109 modeled Cogs are `MODELED_UNVERIFIED`; no Cog is `VERIFIED`.
- A duel recommendation currently carries 16 blockers and reports
  `release_eligible: false`.

No recommendation the engine can produce today is release-eligible, which is the
behavior P0-012 and P0-052 require while measurement is outstanding.

## Schema cost

The five-node numeric AST frozen in P0-023 absorbed the whole item catalogue
without a new node: 201 effect documents and 311 programs are expressed by it,
and the count of items with an unrepresented core effect is zero. Temporal
behavior stayed behind named handlers as that review decided.

That is the strongest available evidence that the schema is neither too small
nor too large, and it is why this review does not reopen it. The schema absorbed
a 29x increase in curated items (7 to 201) with zero structural change.

## Why Phase 1 rather than another Phase 0 pass

Phase 0 asked whether a locked-data engine can produce three deterministic
branches with traceable evidence. It can, and it has done so well past the
single champion and single scenario the milestone scoped:

- Arbitrary matchups run, not just the fixture duel.
- Five-versus-five encounters run, with the actor's own contribution separated
  from its allies' so a build is ranked on what it changes.
- The search is deterministic under parallel execution: worker count cannot
  alter a result.

Repeating Phase 0 would re-derive answers already in hand. Shrinking the schema
would discard expressive power the catalogue demonstrably uses.

## What blocks the gate, and what does not

Blocked on a human at a game client, not on code:

- `P0-041` CC fact verification needs a two-player custom game on 16.17.1. The
  measurement protocol and empty result form are already fixed in
  `docs/verification/cc-blind-16.17.1.md` and
  `fixtures/measurements/cc_blind_16.17.1.pending.json`.
- `P0-035` passes its automated suite; only promotion awaits measured goldens.
- `P0-051` and `P0-052` cannot emit release-eligible output until the facts they
  depend on are promoted.

Not blocking, and deliberately left open:

- `P0-023` lacks per-item timings for the first two items. The forecast is
  usable without them and the gap does not affect engine work.

## Next steps

1. Run the 16.17.1 measurement session. It is the only work that moves the M0
   gate, and every other blocked task depends on it.
2. Continue `P1-064`: promote the remaining 64 scaffolded Cogs. Depth per
   champion is the constraint; the batch that produced shallow single-ability
   Cogs was reverted once already and must not be repeated.
3. Continue `P1-065` follow-ups: chassis metrics still measure against the
   primary opponent alone, and the team arrival distance has no evidence behind
   its default.
4. Widen area abilities beyond the four promoted Cogs, keeping reach bounded by
   line rather than by the whole opposing side.
