# P0-023 effect-schema cost review

- Review date: 2026-09-07
- Input: seven curated items on locked patch `16.17.1`
- Decision: freeze the five-node numeric AST; keep temporal behavior behind named handlers
- Measurement confidence: low for human-time forecasting

## Observed schema cost

| Metric | Result |
|---|---:|
| Curated items | 7 |
| Supported numeric effects | 5 |
| Named exception handlers | 5 |
| New numeric AST nodes | 0 |
| New closed effect operations | 2 |
| New effect classifications | 1 |
| Raw passives with no representation or exception | 0 |
| Record lines, median | 63 |
| P0-022 agent-assisted batch wall time | about 18 minutes |

The five new records average about 3.6 minutes each inside the measured batch,
but that number includes shared schema and test work and excludes an independent
human live-client review. It is not a manual-curation median.

The first two records were created before per-item timing instrumentation. There
is therefore no honest seven-item median authoring time. This specific completion
criterion is blocked by missing historical measurement; reconstructing it from
file size or timestamps would manufacture precision.

## Coverage and omissions

The locked Data Dragon passive text was checked against each item record. Each
passive is in one of two explicit states:

1. an effect whose value is executable by the restricted expression evaluator;
2. a versioned named handler with trigger, behavior contract, numeric parameters,
   and locked source references.

The resulting omission count is zero at the transcription layer. This does not
make any record verified: all seven remain `CURATED_UNVERIFIED`, and no result is
release-eligible.

## Decision

Do not add stack, duration, threshold, clamp, or conditional nodes to the numeric
AST now. The spike did not encounter missing arithmetic; it encountered temporal
state. Adding arithmetic syntax would not solve target-owned stacks, attack
counters, combat timers, cooldown transitions, or end-of-combat expiry.

Keep the current exception boundary through the first end-to-end scenario. Revisit
promotion only after handler implementations reveal a repeated state-machine
shape in at least two items. In particular, Black Cleaver and Riftmaker both have
stacks but do not yet prove a shared abstraction: one owns a target armor debuff
and refreshes on damage events, while the other derives a self buff from elapsed
combat time and unlocks another effect at cap.

The central handler enum is intentionally an authoring gate. Its growth is a
visible maintenance cost; silently accepting arbitrary handler strings would make
missing runtime implementations discoverable too late.

## Next-30 forecast

The only measured throughput gives a lower-bound authoring estimate of about
108 minutes for 30 items (`30 × 3.6`). Allowing 1.5–2.5× for item-specific source
inspection and corrections gives an **authoring range of 2.7–4.5 hours**. Human
verification time is unknown and must be reported separately, so this is not a
promise that 30 verified items fit that range.

Before the next curation batch, create a log containing item ID, author start/end,
reviewer start/end, correction count, and schema-change count. After at least
seven independently timed items, replace this range with a median and percentile.

## Gate impact

The representation decision is complete and supports continuing into the numeric
engine. P0-023 remains blocked only on its historical per-item median condition;
the missing measurement does not justify stopping unrelated Week 3 work.
