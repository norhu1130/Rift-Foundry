# Blind interaction measurement protocol — patch 16.17.1

## Purpose

Measure the response-channel interactions for champion blind in the locked
patch. Static tooltips and an absence of later patch-note mentions are not
accepted as observations.

## Locked targets

- source: Teemo `TeemoQ`, Blinding Dart, rank 5;
- target: Jax, level 13;
- map: Summoner's Rift multiplayer Practice Tool;
- removal item: Quicksilver Sash, item ID `3140`;
- summoner spell: Cleanse, spell ID `SummonerBoost`;
- capture: 60 FPS or better, with the target status bar and attack results visible;
- patch shown by the client: `16.17.1`.

The locked Community Dragon record contains `BlindDuration` values whose five
playable rank entries are 2.0, 2.25, 2.5, 2.75, and 3.0 seconds. The locked Data
Dragon record identifies Cleanse at a 240-second cooldown and Quicksilver Sash
as purchasable on map 11. These values select the experiment; they do not prove
the interactions.

## Timing convention

For duration cases, start at the first frame where the blind icon appears and
stop at the first frame where that icon is absent. Using the first normal basic
attack as the endpoint is forbidden because attack windup and attack cadence
would contaminate the CC duration. Repeat each case five times. Preserve every
raw frame count; do not enter only an average.

## Cases

| Case | Setup and action | Cell measured |
|---|---|---|
| B0 | No tenacity or removal. Teemo lands rank-5 Q; Jax continuously issues attacks. | baseline duration |
| B1 | Equip exactly one known tenacity source. Repeat B0. | `tenacity_reducible` |
| B2 | No tenacity. Activate Cleanse after the blind icon appears. | `cleanse_removable` |
| B3 | No tenacity. Activate item 3140 after the blind icon appears. | `qss_removable` |
| B4 | On a separate Olaf target, activate rank-1 R before Q lands; record both Q damage and whether attacks are blinded. | `immunity_resistible` |
| B5 | Equip exactly one slow-resistance source but no tenacity. Repeat B0. | `slow_resistance_applies` |
| B6 | With zero passive stacks, issue one Jax basic attack while blinded and inspect the passive stack/buff state. | auxiliary `blinded_attack_grants_jax_passive_stack` |

For B5, a duration difference larger than one captured frame indicates that the
auxiliary response affected the blind; equality within one frame indicates no
observed effect. Anything between consistent outcomes remains ambiguous rather
than being rounded into `false`.

## Controls

- Do not combine tenacity sources in B1.
- Reset cooldowns only between repetitions, never during a timed interval.
- Keep champion level, spell rank, items, runes, and latency region unchanged.
- Record the exact tenacity source and displayed tenacity percentage.
- Use Mercury's Treads (item `3111`) as the sole B1 tenacity source.
- Use Boots of Swiftness (item `3009`) as the sole B5 slow-resistance source.
- If the active cannot be triggered while blinded, record that observation
  separately; do not silently convert it into `false` for removal.
- Repeat every case five times. If results disagree, leave the cell `UNVERIFIED`
  and attach all repetitions.
- B6 does not modify the generic blind fact. It gates the Jax dynamic
  attack-speed rotation used by the first scenario.
- B4 is a generic blind-immunity interaction and intentionally overrides the
  default Jax target with Olaf. It is not evidence about Jax's kit.

## Promotion rule

A cell can become `VERIFIED` only when the raw observation artifact is checked
in, its patch and setup match this protocol, and the observed boolean is
reviewed. The complete CC record remains `UNVERIFIED` until every required cell
has verified evidence.

Validate the pending or completed artifact with:

```console
.venv/bin/python -m lol_build.scenarios.measurement \
  fixtures/measurements/cc_blind_16.17.1.pending.json --root .
```
