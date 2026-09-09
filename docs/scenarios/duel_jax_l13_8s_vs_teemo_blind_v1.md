# Jax level 13 vs. Teemo blind benchmark v1

## Purpose

This is the first deterministic schema and engine fixture. It exercises an
auto-attack-dependent fighter, Cleanse as an available response channel, item
tenacity as a separate response channel, and a timed blind event.

It is not yet release evidence. The scenario, target snapshot, damage mix, and
blind interactions remain unverified until custom-game measurements are stored.

## Locked inputs

- Patch and region: KR 16.17.1
- Actor: Jax (ID 24), top, level 13, Flash (4), Cleanse (1)
- Target and CC source: Teemo (ID 17), level 13
- Target items: Nashor's Tooth (3115), Wit's End (3091)
- Blind: rank-5 Blinding Dart at 1000 ms

Data Dragon contains the champion base stats, item identity, and summoner spell
identity. Community Dragon's locked Teemo BIN has the rank-5 blind duration of
3.0 seconds at:

```text
Characters/Teemo/Spells/TeemoQAbility/TeemoQ
  .mSpell.DataValues[name=BlindDuration].values
```

## Derived target snapshot

Until measured in the client, level growth uses the documented community formula:

```text
growth multiplier = (level - 1) * (0.7025 + 0.0175 * (level - 1))
level 13 multiplier = 10.95
```

For Teemo at level 13:

```text
HP    = 615 + 104 * 10.95                   = 1753.8
Armor = 24  + 4.5 * 10.95                  = 73.275
MR    = 30  + 1.3 * 10.95 + 45 (Wit's End) = 89.235
```

These values deliberately carry `DERIVED_UNVERIFIED`, not `VERIFIED`.

## Damage mix

The 30% physical / 70% magical split is an explicit first-scenario benchmark,
not a claim about average Teemo damage or an extracted match statistic. It keeps
the defense branch deterministic before the Teemo rotation model exists.

After the target rotation is implemented, replace it with a derived mix and keep
the benchmark only as a regression fixture if still useful. A release-eligible
scenario cannot use `ASSUMED_BENCHMARK` without an explicit product policy.

## Measurement TODO

1. Create the custom game using the reproduction recipe in the fixture.
2. Record the target stat panel and replace the snapshot status with `VERIFIED`.
3. Measure blind duration with and without each response source.
4. Store raw recordings or timestamped observations and their hashes.
5. Complete the four-step mechanic verification record for `cc_blind_v1`.
