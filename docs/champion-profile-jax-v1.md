# First champion profile — sustained melee on-hit benchmark

The first profile uses Jax as its data identity, but its runtime policy is keyed
by mechanics: sustained/on-hit duelist, mana resource, melee range, an
attack-speed-driven basic-attack schedule, an ability attack reset, and an
every-third-attack proc. Changing the profile's champion ID or display name does
not change the extracted policy.

At level 13 the benchmark assumes Q1/W5/E5/R2. That legal allocation is marked
`ASSUMED_BENCHMARK`; it is not claimed as a universal skill order. The rotation
starts already in range, so Q damage is excluded. R active is also excluded
until its damage and defensive-state coupling are simulated together.

Every modeled damage variant stores playable-rank base values, cooldowns,
scalings, and a path into the locked Community Dragon Jax bin
snapshot. Sentinel ranks from the raw seven-entry arrays are not copied into
the five- or three-rank gameplay arrays.

Per-spell mana costs are deliberately absent. Riot patch 26.12 changed Jax Q
mana from 65 to 50, while the locked 16.17 Community Dragon field still says
65. Until that source conflict is resolved, the profile enforces only the
champion-level `MANA` resource constraint and cannot claim resource-exhaustion
simulation.

Attack speed and W cooldown remain independent. Attack speed schedules basic
attacks; W is scheduled from its own cooldown and separately resets an attack.
No rule claims that attack speed reduces W cooldown or directly increases W cast
frequency.
