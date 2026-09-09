# Champion Cog runtime

The runtime follows the same ownership boundary as a `discord.py` Cog: each
champion extension owns its mechanics, while the registry and matchup engine own
lifecycle, routing, and composition. A Cog is role-neutral. `ParticipantContext`
binds it to `ACTOR` or `TARGET` only for one request.

## Evaluation flow

1. `ChampionCogRegistry` resolves both participant aliases.
2. `MatchupEngine` aggregates each side's static item stats and opponent auras.
3. Both Cogs independently build `ActionPlan` and `ReactionPlan` values.
4. The engine finds a fixed point for causal cast-block windows. A cancelled CC
   source cannot keep cancelling the other participant's actions.
5. `item_combat` converts each owner's declarative item programs into triggers
   derived from the surviving champion and opponent actions.
6. `timeline` replays the merged immutable events and returns an audit log.
7. `cog_preview` evaluates legal one-, two-, and three-core prefixes and retains
   independent damage, survival, engagement, sustain, and chassis frontiers.

Permanent item tenacity shortens only explicitly reducible statuses and cast
windows. Airborne remains unchanged. Slow resistance changes slow magnitude,
not its duration. Temporary tenacity is represented as a timeline stat modifier;
its effect on precomputed cast-block windows remains an explicit non-release
blocker until those windows are promoted to runtime events.

## Extension contract

A specialized Cog overrides only the mechanics it knows:

- `snapshot()` for champion-native permanent stat assumptions;
- `build_action_plan()` for outgoing actions;
- `build_reaction_plan()` for shields, mitigation, and control windows;
- engagement and lane-sustain hooks for non-combat metrics;
- `item_candidate_blocker()` when the Cog cannot value a stat family.

Unknown champions still use the base Cog's deterministic basic-attack fallback.
That keeps arbitrary pairings executable without presenting an uncurated result
as release-ready.

Every class and callable under `src/lol_build` has an English docstring. Every
callable documents each argument with `:param:` and its result with `:return:`;
public error boundaries additionally use `:raises:` where relevant. The
repository-wide contract is enforced by `tests/test_api_documentation.py`.

## Selection boundary

The generic beam does not collapse every metric into one invented scalar.
Independent axis frontiers are retained at each core. Hard readiness gates cover
contact, chassis growth, conditional item availability, unique groups, boots,
and cumulative budgets. Branch selection is deterministic and tie-breaks by
completion cost, total gold, and item IDs.

All current generic previews remain `INSUFFICIENT_EVIDENCE` and
`release_eligible=false` while any champion formula, hit timing, or connected
item state is unverified.
