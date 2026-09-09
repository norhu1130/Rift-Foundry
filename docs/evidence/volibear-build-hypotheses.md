# Volibear expert-build evidence triage

- Review date: 2026-09-07
- Original video: [5년 동안 깎은 빌드](https://www.youtube.com/watch?v=hm2wkTIuj1c)
- Creator: ㅇyㅇ
- Published: 2025-12-19
- Duration: 2:49:52
- Historical Data Dragon build used for ID checks: `15.24.1`
- Input summary status: `UNTRUSTED_DERIVATIVE`

## Use policy

The supplied English summary is not evidence and is not a recommendation fixture.
It mixed item names, Korean abbreviations, runes, research-stage builds, and the
final build. This document keeps only testable hypotheses and provenance.

The auto-generated Korean transcript is useful for locating claims but is not a
locked numeric source. Any claim promoted into runtime data still needs an exact
snapshot, hash, patch attribution, and human review.

## Source identity and chapter map

The original source was recovered from its distinctive build names. Its published
chapter markers distinguish experiments from the final build explanation:

| Timestamp | Original chapter | Normalized meaning |
|---:|---|---|
| 10:27 | 칠흑 우추 빌드 | Black Cleaver + Cosmic Drive experiment |
| 15:36 | 강심 빌드 | Heartsteel experiment |
| 20:26 | 얼건 빌드 | Iceborn Gauntlet experiment |
| 22:38 | 칠흑 망자 빌드 | Black Cleaver + Dead Man's Plate experiment |
| 34:30 | 영겁 빌드 | Rod of Ages experiment |
| 48:47 | 영겁 기맹 빌드 | Rod of Ages + Knight's Vow experiment |
| 2:23:47 | 다이소 빌드 총정리 | Final component-first build explanation |

The supplied summary flattened these stages into one recommendation. That
transformation is rejected.

## Item-ID corrections

IDs below were checked against Riot Data Dragon `15.24.1`, the build available
for the video's release-period patch.

| Korean source term | Correct item | ID | Summary corruption |
|---|---|---:|---|
| 칠흑 | Black Cleaver | 3071 | Mapped to Ravenous Hydra |
| 우추 | Cosmic Drive | 4629 | Omitted or merged into another item |
| 망자 | Dead Man's Plate | 3742 | Mapped to Wit's End |
| 영겁 | Rod of Ages | 6657 | Rendered as an unclear “영급” build |
| 기맹 | Knight's Vow | 3109 | Rendered as Guardian's Blessing |
| 강심 | Heartsteel | 3084 | Not kept distinct as an experiment |
| 얼건 | Iceborn Gauntlet | 6662 | Not kept distinct as an experiment |
| 혹한의 손길 → 종말 | Winter's Approach → Fimbulwinter | 3119 → 3121 | Merged with Thornmail/Dead Man's Plate |
| 얼심 | Frozen Heart | 3110 | Mapped to Spirit Visage |
| 정령 | Spirit Visage | 3065 | Shifted onto another abbreviation |
| 절망 | Unending Despair | 2502 | Correct concept, but mixed with other core labels |
| 카탈 | Catalyst of Aeons | 3803 | Component and completed Rod of Ages were conflated |
| 가속신/쿨감신 | Ionian Boots of Lucidity | 3158 | Interpreted as attack-speed acceleration |

The final summary section of the source describes a core centered on Fimbulwinter,
Frozen Heart, Spirit Visage, and later Unending Despair. Zhonya's Hourglass,
Sterak's Gage, Black Cleaver, and Spear of Shojin appear as situational later
choices, not as the four-item core claimed by the supplied English summary.

Rune and summoner-spell mappings from the supplied summary remain
`SOURCE_NOT_REVIEWED`. They must not be inferred from mistranslated parenthetical
labels.

## Hypothesis register

| ID | Claim | Status | Next valid test |
|---|---|---|---|
| VOLI-H01 | Ability haste shortens the W recast cycle and changes repeated-W availability. | `SOURCE_AND_DATA_SUPPORTED` | P0-032 cooldown calculation, then timeline test |
| VOLI-H02 | Attack speed directly increases W cast frequency. | `REJECTED_SOURCE_ATTRIBUTION` | Reopen only if an exact source timestamp or game mechanic is supplied |
| VOLI-H03 | Attack speed may improve auto-attack DPS, passive stacking, or the ability to stay in contact with a W-marked target. | `UNVERIFIED_SEPARATE_CLAIM` | A scenario with movement, autos, and passive stacks |
| VOLI-H04 | Fimbulwinter health/shields, Frozen Heart armor, Spirit Visage amplification, and Unending Despair healing produce complementary durability. | `UNVERIFIED_CALCULATION_HYPOTHESIS` | Stateful 8-second survival timeline |
| VOLI-H05 | Filling slots with efficient components before rapidly completing cores improves intermediate purchase states. | `TRANSCRIPT_SUPPORTED_OUT_OF_V1` | Ordered shop-state model in v1.5 |
| VOLI-H06 | Silence can remove both damage and healing when both are outputs of a prevented W event. | `EVENT_MODEL_HYPOTHESIS` | Cancel a scheduled W event and verify both outputs disappear |
| VOLI-H07 | Some opponent profiles have no feasible item response under a fixed scenario and budget. | `UNVERIFIED_SCOPED_HYPOTHESIS` | `NO_FEASIBLE_ITEM_RESPONSE` with explicit failed requirements |
| VOLI-H08 | Ranged poke requires a lane-sustain objective not represented by the stationary 8-second duel. | `OUT_OF_MODEL_HYPOTHESIS` | Deferred lane scenario |

## “Attack speed → W frequency” verdict

The supplied summary appears to have translated Korean `가속` as generic
“acceleration” and then reinterpreted it as attack speed. The source instead
associates it with Ionian Boots, Kindlegem, cooldown reduction, and repeated
spell use. Searches of the recovered transcript found no `공속` or `공격 속도`
claim.

Data Dragon `15.24.1` records Frenzied Maul with a five-second base cooldown at
all ranks and no attack-speed scaling in its spell description. Therefore:

- ability haste affecting W availability is a valid calculation hypothesis;
- attack speed directly changing W cooldown is rejected;
- any indirect attack-speed value belongs to a separate auto/passive/contact
  hypothesis and must not be relabeled as W cooldown reduction.

## Scope guardrails

The project objective remains recommendation, not retrospective explanation:

> v1 derives a build inside one explicit combat scenario. It does not claim to
> reproduce an expert's full build across long lane states, component ordering,
> skill differences, and every matchup.

When expert evidence conflicts with the model, keep the objective fixed and
classify the mismatch as model error, unsupported scope, insufficient evidence,
or an unverified hypothesis. Do not move the success criterion after seeing the
result.

Before adding a new objective axis, first attempt to represent the behavior with
existing timeline events and their outputs.
