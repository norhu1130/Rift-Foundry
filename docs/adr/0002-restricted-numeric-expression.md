# ADR-0002: Restricted numeric expression tree

- Status: Accepted
- Date: 2026-09-07

## Decision

Only the numeric portion of item and champion effects uses an expression tree.
Version 1 has five nodes:

- `CONSTANT`
- `STAT`
- `ADD`
- `MULTIPLY`
- `LEVEL_CURVE`

Triggers, target selection, and conditions remain closed enums in their owning
effect schemas. Expressions cannot contain source code, function names, or text
that is evaluated at runtime.

`STAT` identifies an entity (`SELF` or `TARGET`), a basis (`BASE`, `BONUS`,
`TOTAL`, `CURRENT`, `MAX`, or `MISSING`), and a supported statistic. Decimal
constants are strings and level curves contain exactly 18 values.

## Node admission rule

Before adding a general node, record how many currently curated effects need it.
If exactly one effect needs the behavior, prefer an explicit, named exception.
Promote the exception to a node only when reuse or composition justifies the
additional authoring and validation cost.

An exception must be a versioned identifier handled by ordinary typed code. It
must never be an arbitrary expression, callback, or dynamically imported module.
Each exception record also carries a closed trigger, an auditable behavior
contract, expression-validated numeric parameters, and locked source references.
Until its named handler exists, the evaluator reports the identifier but does not
produce a numeric result for it.

## Consequences

- Division, min/max, clamps, stack counts, and conditional expressions are not
  available in v1.
- An item that needs an unsupported operation remains unsupported or gets a
  reviewed named exception; curators must not approximate its value.
- The intentionally small tree measures real schema pressure during the first
  seven-item spike before the language grows.
