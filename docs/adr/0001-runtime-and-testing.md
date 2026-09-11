# ADR-0001: Runtime and testing conventions

- Status: Accepted
- Date: 2026-09-07

## Decision

The engine uses Python 3.12 or newer and `uv` for dependency locking and command
execution. The supported command for local and CI verification is:

```sh
uv run pytest && uv run ruff check . && uv run ruff format --check .
```

> **Enforcement status (2026-09-11):** `ruff format --check .` is part of the
> decided command but is not yet enforced — 151 files currently fail it. Until
> a single formatting-only commit lands, the working gate is
> `uv run pytest && uv run ruff check .` (see `README.md`). The formatting
> commit must not be mixed with behavior changes.

JSON Schema uses draft 2020-12 and the Python `jsonschema` implementation.
`pytest` is the test runner and `ruff` is the formatter and static lint gate.

## Numeric policy

- Domain calculations use `decimal.Decimal` with explicit string construction.
- Binary `float` values are rejected at calculation and output boundaries.
- The default calculation context is precision 28 and `ROUND_HALF_EVEN`.
- Each formula test defines its own absolute and/or relative error tolerance.
- Damage displayed as an in-game integer is not rounded until the formula's
  documented rounding boundary.
- Non-finite numbers are invalid.

## Deterministic output policy

- Object keys are sorted.
- JSON uses compact separators and UTF-8 characters without ASCII escaping.
- `Decimal` output values are normalized non-exponent strings with no trailing
  fractional zeroes. Negative zero is serialized as `"0"`.
- Arrays retain their domain-defined order. Sets must be sorted before entering
  the output model.
- Ties use explicit stable domain keys; collection iteration order is never a
  tie-breaker.

## Dependency and network boundary

- Network access is allowed only in explicit build-time data-fetch commands.
- Runtime engine modules must not import HTTP clients.
- Tests run against locked local fixtures and must pass without network access
  after dependencies have been installed.
- Dependencies are committed through `uv.lock`; unconstrained ad-hoc installs
  are not part of the workflow.

## Rationale

Python keeps the first vertical slice small, while `Decimal`, JSON Schema, and
property-oriented pytest tests cover the calculation and data-contract risks.
The project does not currently need a browser runtime or a compiled service.

## Consequences

- Decimal values in result JSON are strings rather than JSON numbers.
- A later UI or API layer must preserve these strings or perform an explicitly
  documented presentation conversion.
- If performance measurements fail the one-second target, optimize measured hot
  paths before considering a runtime migration.

