# Calculated but unverified Jax rotation preview

The non-release preview no longer uses arbitrary AD/AP/attack-speed damage
weights. It reads the locked Jax base stats, level growth, passive attack-speed
breakpoints, W/E/R damage and cooldown records, and curated item expression
trees. It schedules basic attacks dynamically, applies W as an attack reset,
casts E once, and attaches R passive damage to every third successful hit.

Three timing and interaction claims remain unverified: the exact W reset timing,
whether a blinded missed attack grants a Jax passive stack, and how a missed
empowered/every-third attack consumes its state. The engine therefore evaluates
both possible passive-stack outcomes. It reports whether all three selected
item orders are stable across those variants, but neither stability nor source
agreement promotes the result to release evidence.

The current three-item preview is stable across the two miss-stack variants:

- default/offense: Nashor's Tooth → Mercury's Treads → Jak'Sho;
- defense: Jak'Sho → Mercury's Treads → Nashor's Tooth.

These paths validate pipeline behavior only. Jak'Sho's delayed passive is not
yet evaluated, all three curated items remain unverified, and the output remains
`INSUFFICIENT_EVIDENCE` / `SYNTHETIC_NON_RELEASE`.
