# P0-022 item expression coverage

- Patch lock: KR `16.17.1`
- Recorded: 2026-09-07
- Curated set: 7 items
- Verification status: all `CURATED_UNVERIFIED`

## Coverage result

| Item | Pressure tested | Directly represented | Named exception |
|---|---|---|---|
| Mercury's Treads (3111) | Tenacity, purchase group | Base stats | None |
| Sterak's Gage (3053) | Base-stat conversion, threshold shield, ranged modifier, shared cooldown | Both passives | None |
| Black Cleaver (3071) | Stack gain/refresh/expiry, target debuff, ranged timed buff, purchase group | Base stats | `black_cleaver_carve_v1`, `black_cleaver_fervor_v1` |
| Nashor's Tooth (3115) | Additive on-hit formula | `15 + 0.15 × total AP` | None |
| Blade of the Ruined King (3153) | Target current-health ratio, melee/ranged split, attack counter | Mist's Edge | `blade_ruined_king_clawing_shadows_v1` |
| Riftmaker (4633) | Bonus-health conversion, elapsed-combat stacks and expiry | Void Infusion | `riftmaker_void_corruption_v1` |
| Jak'Sho, The Protean (6665) | Delayed activation and end-of-combat expiry | Base stats | `jaksho_voidborn_resilience_v1` |

Every passive visible in the locked Data Dragon record is either represented by
an executable expression or listed as a named exception. Nothing unsupported is
approximated as a constant bonus.

## Expression-node use

Counts below are the number of supported effects whose expression tree uses the
node at least once, across the seven-item set.

| Node | Effects using it | New in this spike |
|---|---:|---|
| `CONSTANT` | 7 | No |
| `STAT` | 5 | No |
| `ADD` | 1 | No |
| `MULTIPLY` | 5 | No |
| `LEVEL_CURVE` | 0 | No |

No expression node was added. Target-current-health damage composes the existing
`STAT(TARGET, CURRENT, HP)` and `MULTIPLY` nodes. The exact 9% melee / 6% ranged
split uses a 6% base expression and the existing 1.5 melee modifier.

The item effect vocabulary gained two narrow operations
(`GRANT_BONUS_AP`, `DEAL_PHYSICAL_DAMAGE`), one effect classification
(`PCT_CURRENT_HP_DAMAGE`), and the `LIFESTEAL` base stat. These are closed enum
values, not new expression-language features.

## Exception decisions

Five handlers cover four items. They were not promoted to generic nodes because
each requires temporal or target-owned state, while the expression tree is
deliberately stateless:

- Black Cleaver Carve owns stacks on each damaged target and refreshes expiry.
- Black Cleaver Fervor grants and refreshes a timed range-dependent stat buff.
- Clawing Shadows counts attacks in a time window, then starts a cooldown.
- Void Corruption derives stacks from elapsed champion-combat time and grants a
  max-stack-only stat until combat ends.
- Voidborn Resilience activates after a combat-time threshold and expires with
  the combat state.

Each record preserves the relevant numeric parameters and source locations.
Runtime evaluation exposes the handler name without evaluating it, so missing
state-machine support is observable.

## Group separation

The schema continues to model `purchase_limit`, `same_passive`, and
`shared_cooldown` independently. Black Cleaver records the locked
`LastWhisper` purchase group as normalized `last_whisper`; Sterak's keeps
Lifeline in all three fields because the locked data assigns all three
constraints to that passive. Group semantics remain unverified until candidate
generation work validates them against the client.

## Curation-time record

The five-item P0-022 batch took approximately **18 minutes of agent-assisted wall
time**, including schema changes, records, and tests. This is a batch measurement,
not five independently timed manual samples. The two P0-015 records predate timing
instrumentation, so a defensible per-item median cannot yet be calculated.

This limitation is carried into P0-023: its cost decision must distinguish the
observed agent-assisted batch time from human review time and must not present a
fabricated median. Future records need explicit `started_at`, `completed_at`, and
review minutes in a curation log.

## Result

P0-022 passes its expression-coverage objective without enlarging the numeric
AST. The spike also confirms that temporal state—not arithmetic expressiveness—is
the next schema pressure point. Whether to implement any exception generically is
deferred to the P0-023 cost review.
