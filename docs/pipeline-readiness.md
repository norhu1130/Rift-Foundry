# Recommendation pipeline readiness gate

The runtime checks scope and evidence before generating any objective vector. New recommendation
documents expose three orthogonal state axes because a build can be found while its evidence is
still incomplete:

- `state.outcome`: `FOUND` or `NO_FEASIBLE`;
- `state.verification`: `VERIFIED` or `INSUFFICIENT_VERIFICATION`;
- `state.scope`: `IN_SCOPE` or `OUT_OF_SCOPE`.

The legacy `recommendation_status` field remains during API migration:

- `READY`: every dependency needed for scoring is verified;
- `NO_FEASIBLE_ITEM_RESPONSE`: verified scoring ran, but no candidate met the
  scoped feasibility requirements;
- `INSUFFICIENT_EVIDENCE`: one or more required scenario, champion, mechanic,
  or item facts are not verified;
- `OUT_OF_SCOPE`: the requested encounter is outside the implemented scenario
  contract.

`INSUFFICIENT_EVIDENCE` and `OUT_OF_SCOPE` must never be phrased as “items cannot solve this
matchup.” A v1 preview also emits `assumptions.game_state = NOT_MODELED`; it does not claim equal
gold or experience merely because both participants use the same benchmark level.

Run the current gate offline with:

```console
.venv/bin/python -m lol_build.recommendation.readiness --root .
```

The output is canonical JSON. The command reads only locked and curated local
files and imports no network client.
