# P0-050 first champion profile report

## Result

The mechanic-keyed Jax profile is structurally complete but remains
`CURATED_UNVERIFIED`. Its damage bases, damage coefficients, and cooldowns point
to the locked 16.17.1 Community Dragon snapshot.

## Source conflict

Riot patch 26.12 explicitly changed Leap Strike mana from 65 to 50. The locked
Community Dragon 16.17 Jax bin still contains 65 in its Q mana array. No later
reversion was established.

The profile therefore omits every per-spell resource cost instead of mixing a
known-conflicted Q cost with apparently current costs from the same raw record.
The `MANA` resource type remains sufficient for item candidate legality, but
resource-exhaustion simulation is outside the profile's verified capability.

## Non-coupling rule

Attack speed schedules basic attacks. W uses its own cooldown and is separately
tagged as an attack reset. The profile contains no rule that converts attack
speed into W cooldown or cast frequency.
