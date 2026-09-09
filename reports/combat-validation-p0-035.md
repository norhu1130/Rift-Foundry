# P0-035 combat validation status

- Patch: `16.17.1`
- Automated status: `PASS`
- Client measurement status: `BLOCKED`

## Automated coverage

- calculated golden cases for positive, zero, and negative resistance;
- zero, 100, and 900 ability haste;
- physical, magical, true, and mixed-damage EHP;
- resistance and cooldown monotonicity;
- deterministic event ordering and horizon inclusion;
- shield absorption before HP loss, healing caps, and death-state derivation;
- no intermediate rounding in engine calculations.

## Measurement error policy

- One displayed integer-damage event: absolute error at most 1 damage.
- Accumulated damage: relative error at most 1 percent.
- An accumulated measured value of zero must match exactly, because relative
  error is undefined.

Comparison output retains calculated value, measured value, absolute error,
relative error where defined, tolerance type, and pass/fail status.

## Blocker

No live-client observation exists for the reproducible Jax-versus-Teemo fixture.
The repository cannot manufacture that external measurement. The fixture remains
`DERIVED_UNVERIFIED`, and combat formulas remain `CURATED_UNVERIFIED`.

To unblock, record the locked `16.17.1` client build executing the recipe in
`docs/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.md`, capture displayed HP and
damage observations, and add a measurement artifact referenced by the fixture.
The comparison code can then report the actual differences without changing its
tolerances after seeing the result.
