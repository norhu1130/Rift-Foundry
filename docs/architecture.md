# Package architecture

`lol_build` is split by responsibility rather than champion or file type. Feature modules
must not be added directly under the package root.

| Package | Responsibility |
|---|---|
| `core` | Exact numeric expressions, combat formulas, timeline events, CC, validation |
| `items` | Locked item catalog, effects, candidate generation, build progression |
| `cogs` | Role-neutral champion behavior and champion registry |
| `scenarios` | Scenario contracts and client-measurement evidence |
| `simulation` | Rotation schedulers that execute against core combat types |
| `recommendation` | Readiness, Pareto selection, responses, and provenance |
| `application` | Matchup dispatch and preview use cases that compose all lower layers |
| `buildtime` | Snapshot fetching, patch-lock validation, and drift reporting |

The intended dependency direction is toward `core`. `application` is the composition root
and may depend on every package. `cogs` may depend only on `core` and `items`: no champion
or matchup pair receives special-cased application- or simulation-layer logic. Champion
behavior lives entirely inside that champion's own Cog.

The boundary contract is executable in `tests/test_package_architecture.py`.
