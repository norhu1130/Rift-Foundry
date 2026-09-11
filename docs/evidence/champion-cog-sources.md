# Champion Cog evidence boundary

The generic matchup engine is locked to Data Dragon `16.17.1`. Every
registered champion — Aatrox and Ahri included — now has three locked detail
sources (P1-064): the per-champion Data Dragon file, the CommunityDragon
champion JSON, and the CommunityDragon `.bin.json`. Having a locked source is
not the same as having a model derived from it: the Aatrox and Ahri Cogs still
use a synthetic level-13 fixture (`*_level13_synthetic_v1`) that has not been
mechanically diffed against their bins, so they stay `MODELED_UNVERIFIED`.

## Locally locked sources

- `data/raw/16.17.1/en_US/champion.json`: identity and base-stat fallback for
  every registered champion.
- `data/raw/16.17.1/en_US/champion/<Name>.json`,
  `data/raw/16.17.1/communitydragon/champions/<id>.json`, and
  `data/raw/16.17.1/communitydragon/champions/<name>.bin.json`: per-champion
  detail sources, listed in each Cog's `evidence_refs`.
- `darius.bin.json`: Darius spell ranks, ratios, CC, Hemorrhage and Noxian
  Might inputs.
- `garen.bin.json`: Garen Q/E/R/W values and base/growth stats.

## Aatrox change-chain checks

The Aatrox synthetic Cog uses the following official changes as evidence, but
these are deltas rather than a complete current rules table:

- [Patch 25.11](https://www.leagueoflegends.com/en-gb/news/game-updates/patch-25-11-notes/):
  W returned to physical damage and Q sweet-spot damage became 170%.
- [Patch 25.12](https://www.leagueoflegends.com/en-us/news/game-updates/patch-25-12-notes/):
  E champion-damage healing became 16% plus 1.1 percentage points per 100
  bonus health; passive healing versus champions became 100% of its damage.
- [Patch 26.2](https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-2-notes/):
  passive target-max-health damage changed to 4-10% by level.
- [Patch 26.12](https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-12-notes/):
  Q sweet-spot bonus damage changed from 70% to 75%.

These sources support individual changes only. They do not prove that no later
hotfix changed an unmentioned field. The 16.17 detail bin is now locked, but
`AATROX_FORMULAS_CURATED_UNVERIFIED` and the timing/hit blockers remain until
the synthetic values are mechanically diffed against it.

## Ahri boundary

Ahri's detailed spell bin is now locked, but the Q/W/E/R action values are
still a deterministic synthetic fixture that has not been diffed against it. `AHRI_FORMULAS_CURATED_UNVERIFIED`, hit assumptions, charm
timing and passive-heal omission remain release blockers.

## Promotion rule

Patch notes may corroborate one edge in the chain but never replace a current
rules snapshot. Promotion requires:

1. exact patch detail source;
2. parsed mechanic record;
3. deterministic engine test;
4. client measurement where the parsed rule remains ambiguous.

