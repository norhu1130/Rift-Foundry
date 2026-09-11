# ADR 0003: Role-neutral champion Cogs

## Status

Accepted and implemented as a non-release Phase 1 capability. Evidence
verification remains Phase 2 work.

## Decision

Champion mechanics are loaded through a `ChampionCogRegistry`, following the
lifecycle shape of discord.py Cogs: the registry owns add/remove/lookup and each
Cog owns one champion's related behavior.

A Cog is role-neutral. It is not an attacker or target class. Every matchup
creates two `ParticipantContext` values and assigns `self_entity` and
`opponent_entity` for that request. Both participants expose the same ports:

```text
ChampionCog
 ├─ snapshot(level, item_stats)
 ├─ build_action_plan(participant_context)
 ├─ build_reaction_plan(participant_context)
 ├─ engagement_speed_multiplier(participant_context)
 ├─ engagement_dash_distance(participant_context)
 └─ item_candidate_blocker(item)
```

This permits the same Garen Cog to occupy either side of `Garen vs Aatrox` and
`Aatrox vs Garen`. Champion-specific action and reaction models can be added
independently. For example, a Garen Cog may later own both his offensive
rotation and his W reaction without changing the dispatcher.

The concrete evaluation flow, CC/tenacity boundary, and public API docstring
contract are specified in `docs/architecture/champion-cog-runtime.md`.

`DariusCog` owns the five-stack rotation directly, with no compatibility entry
points into any other module and no dispatch logic keyed on the opponent. All
orchestration resolves through the Cog interface only.

## Registry and fallback

The default registry materializes every champion in the locked Data Dragon
catalog through an explicit manifest. Names are resolved case-insensitively and
numeric champion IDs are accepted. Every roster entry owns a physical module
and a distinct Cog class. The registry refuses to start when the locked roster
and manifest differ, preventing silent champion omissions after a patch.

Physical module coverage is not treated as behavior coverage. A Cog declares
its maturity and capabilities independently:

- `SCAFFOLDED` Cogs expose only the deterministic basic-attack contract;
- `MODELED_UNVERIFIED` Cogs may expose curated action, reaction, engagement,
  item-policy, or recommendation capabilities;
- `VERIFIED` is reserved for models whose evidence chain has been completed.

The locked roster currently contains 173 dedicated modules. Their maturity is
encoded by folder under `cogs/champions/` (`todo/`, `wip/`,
`modeled_unverified/`, `curated/`) and enforced by
`tests/test_all_champion_modules.py`; current counts live in `README.md`
rather than here, so this ADR does not go stale. Shared event constructors live in `cogs/mechanics` so champion
modules compose damage, healing, shielding, movement, and control without
copying timeline infrastructure.

The fallback is structural, not a release recommendation. Every registered Cog
can invoke the generic preview, but an uncurated Cog still emits these
blockers instead of pretending its spell behavior is known:

- `ROTATION_UNCURATED:<champion>`
- `REACTIONS_UNCURATED:<champion>`

Item programs are no longer globally omitted. The common adapter observes both
participants' action streams and dispatches active-use, attack-hit,
ability-hit, damage-dealt, and damage-received triggers with the owner's
`EntityId`. Unsupported stateful triggers remain item-specific blockers. A
cancelled champion event cannot trigger an item proc.

Garen overrides the action port with a locked level-13 Q5/E5/R2 shape and the
reaction port with synthetic Q cast blocking and W shield/damage-reduction
windows. R uses the timeline's stateful missing-health damage output, so its
value is resolved at cast time. Because all outputs use context entities, the
same implementation follows Garen to either participant slot.

Aatrox and Ahri have explicit synthetic level-13 action and reaction Cogs.
Aatrox Q/W damage, Q airborne windows, E/R-amplified healing and Ahri's AP
rotation, true-damage Q return, charm window, and Spirit Rush mobility therefore
compose in either role. Their formulas and hit/timing assumptions are
`CURATED_UNVERIFIED`, so these results remain non-release.

Cast-block windows reference the action event that caused them. The dispatcher
recomputes cancellation dependencies, so a Q or E cancelled by an earlier
silence/pull cannot still apply its airborne/charm window.

Cogs must explicitly declare the `RECOMMENDATION` capability before the
dispatcher runs any preview. A legacy model-name attribute or a physical module
does not grant that capability. Every actor, with no exception, is ranked by
the same exhaustive three-core search: every legal ordered path is evaluated
with no pruning between cores (P1-067 replaced the earlier bounded beam, which
provably missed optimal paths). Metrics stay separate; the search never
invents one blended score. Each prefix is evaluated at its own completion
budget. The preview exposes pursuit uptime,
mixed-damage EHP, 30-second lane recovery, weighted completion gold, Warmog
readiness, and Heartsteel purchase-time stacks. Default and defense first use
candidates meeting every-core engagement, item-readiness, and chassis floors;
offense remains the unconstrained damage branch.

## Phase 2 evolution

For each newly curated champion:

1. subclass `ChampionCog`;
2. override the action plan, reaction plan, or both;
3. register it with `override=True`;
4. remove only the blockers covered by verified mechanics;
5. enable build recommendation when both participant plans provide all metrics
   required by the requesting champion's objective profile.

No matchup pair class is introduced. Pair-specific interactions are composed
from the two Cogs and an encounter profile, preventing an `N × N` class matrix.

## Command boundary

The role-symmetric structural evaluator is available through:

```text
python -m lol_build.application.matchup Garen Aatrox \
  --actor-items 6631 --opponent-items 3071
```

Adding `--recommend` dispatches to the actor Cog through the same exhaustive
generic preview for every pair, with no matchup-specific exception; it
discloses `ROTATION_UNCURATED` or mechanic-specific blockers when a Cog lacks
enough evidence. Reversing the two command arguments reverses roles; it does
not select a different attacker-only class.
