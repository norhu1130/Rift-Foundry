# Champion Cog evidence boundary

The generic matchup engine is locked to Data Dragon `16.17.1`. Darius and
Garen have local CommunityDragon detail snapshots. Aatrox and Ahri currently do
not, so their Cogs must not be promoted beyond `CURATED_UNVERIFIED`.

## Locally locked sources

- `data/raw/16.17.1/en_US/champion.json`: identity and base-stat fallback for
  every registered champion.
- `data/raw/16.17.1/communitydragon/champions/darius.bin.json`: Darius spell
  ranks, ratios, CC, Hemorrhage and Noxian Might inputs.
- `data/raw/16.17.1/communitydragon/champions/garen.bin.json`: Garen Q/E/R/W
  values and base/growth stats.

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
hotfix changed an unmentioned field. `AATROX_FORMULAS_CURATED_UNVERIFIED` and
the timing/hit blockers therefore remain until the exact 16.17 detail bin is
locked and mechanically diffed.

## Ahri boundary

The local catalog proves Ahri's identity, resource and base stats, but does not
contain her detailed spell bin. The Q/W/E/R action values are a deterministic
synthetic fixture. `AHRI_FORMULAS_CURATED_UNVERIFIED`, hit assumptions, charm
timing and passive-heal omission remain release blockers.

## Promotion rule

Patch notes may corroborate one edge in the chain but never replace a current
rules snapshot. Promotion requires:

1. exact patch detail source;
2. parsed mechanic record;
3. deterministic engine test;
4. client measurement where the parsed rule remains ambiguous.

