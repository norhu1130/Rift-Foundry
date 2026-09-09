# Combat math contract

## Resistance multiplier

The engine currently implements the following piecewise function with `Decimal`:

```text
R >= 0: 100 / (100 + R)
R <  0: 2 - 100 / (100 - R)
```

At zero the two regions meet at multiplier 1. Positive resistance reduces
damage; increasingly negative resistance increases damage and approaches a
multiplier of 2.

Physical damage selects armor, magic damage selects magic resistance, and true
damage selects neither. The engine does not round inside this function. Display
rounding and in-client integer damage comparison belong to the golden-test layer.

## Validation status

Status: `CURATED_UNVERIFIED` for patch `16.17.1`.

The formula is an executable project assumption with boundary tests, not yet a
claim of current-client verification. P0-035 must compare it with a reproducible
practice-tool or custom-game fixture before it can become `VERIFIED`. Until then,
release provenance must expose this status.

## Reduction and penetration pipeline

Version 1 applies these stages in order and records every before/after value:

1. flat resistance reduction;
2. percentage resistance reduction;
3. percentage resistance penetration;
4. flat resistance penetration.

Flat reduction may cross zero. Once the working resistance is non-positive,
percentage reduction and both penetration stages are skipped. Flat penetration
is otherwise floored at zero. Reduction and penetration remain distinct because
the former changes the target-visible resistance while the latter is local to the
attacker's damage calculation.

Bonus-resistance-only reduction and penetration are intentionally absent from
this first contract. They must be introduced as explicit stages if a curated
effect requires them; they must not be folded into the total-resistance fields.

Like the base multiplier, this ordering has `CURATED_UNVERIFIED` status until the
P0-035 client comparison is complete.

## Ability haste

Ability haste is converted without intermediate rounding:

```text
cooldown multiplier       = 100 / (100 + AH)
effective cooldown        = base cooldown × cooldown multiplier
equivalent CDR             = AH / (100 + AH)
```

Effective cooldown and equivalent cooldown reduction are separate output fields.
At zero haste the cooldown is unchanged and equivalent reduction is zero. As
haste grows, effective cooldown approaches zero and equivalent reduction
approaches—but never reaches—100 percent.

Negative haste is outside the Summoner's Rift v1 input contract and is rejected.
The engine accepts a zero base cooldown for totality, though candidate spell
records may impose a stricter positive-cooldown invariant.

## Effective health

Per-channel effective health is health divided by that channel's post-resistance
damage multiplier:

```text
physical EHP = HP / physical multiplier
magical EHP  = HP / magical multiplier
true EHP     = HP
```

For a raw incoming damage mix `(p, m, t)` whose components sum exactly to one:

```text
mixed multiplier = p × physical multiplier
                 + m × magical multiplier
                 + t
mixed EHP        = HP / mixed multiplier
```

The engine does not average physical and magical EHP values. Averaging EHP would
apply the mixture after taking reciprocals and overstate survivability. Mixture
validation rejects negative fractions, fractions above one, non-finite values,
and totals other than exactly one.
