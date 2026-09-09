# P0-041 CC fact verification report

## Result

`BLOCKED` for blind on patch 16.17.1. No interaction cell was promoted from
`UNVERIFIED`.

## Four-step chain

1. **Last located official effect change — partial evidence.** Riot patch 11.21
   changed Teemo Q cooldown, blind duration, and missile speed. This identifies
   the benchmark effect's numeric history, not whether a response channel works
   against it.
2. **Later relevant-change scan — incomplete.** A targeted official-source
   search located patch 14.10's Cleanse cooldown and post-cast tenacity change,
   but it did not establish a complete interaction history through 16.17.1.
   Consequently no `subsequent_change_scan` result is written to the fact.
3. **Locked-client measurement — missing.** This workspace cannot launch two
   clients and observe a custom game. The exact experiment is frozen in
   `docs/verification/cc-blind-16.17.1.md`, with an empty raw-results fixture.
4. **Promotion — withheld.** `verified_patch` remains null, all five interaction
   values remain null, and the record remains `UNVERIFIED`.

## Static cross-checks

- Community Dragon 16.17.1 identifies Teemo Q rank-5 blind duration as 3.0
  seconds (the playable rank entries are indices 1 through 5).
- Data Dragon 16.17.1 identifies Cleanse as `SummonerBoost`, cooldown 240.
- Data Dragon 16.17.1 identifies Quicksilver Sash as item `3140`, purchasable on
  Summoner's Rift.

These checks prevent testing the wrong assets. Their tooltip wording is not
treated as measured interaction evidence.

## Unblock condition

Run and review cases B0–B4 in the locked client, then attach raw frame counts
and recordings. Slow-resistance applicability must also be resolved before the
whole blind record can be globally `VERIFIED`.
