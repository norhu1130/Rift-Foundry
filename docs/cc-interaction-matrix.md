# CC interaction matrix — patch 16.17.1

This matrix is a curation work queue, not a table of remembered game rules. Each
cell mirrors the status stored in `data/curated/mechanics/*.json`. An unknown
interaction is `UNVERIFIED` with a null value; it is never encoded as `false`.

## Response channels

| CC | Tenacity reduces duration | Cleanse removes | QSS removes | CC immunity resists |
|---|---|---|---|---|
| Blind | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |
| Stun | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |
| Slow | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |

## Slow-resistance auxiliary channel

Slow resistance is distinct from tenacity and removal. It remains present in the
machine records because it changes slow magnitude rather than CC duration.

| CC | Slow resistance changes magnitude |
|---|---|
| Blind | `UNVERIFIED` |
| Stun | `UNVERIFIED` |
| Slow | `UNVERIFIED` |

## Action-channel impact

These are classification records, not yet live-client-verified behavior:

| CC | Blocked action channels in the v1 record |
|---|---|
| Blind | Basic attack |
| Stun | Basic attack, ability, movement, item active |
| Slow | Movement |

## Promotion rule

A cell becomes `VERIFIED` only after the P0-041 chain records:

1. the last known change evidence;
2. a subsequent patch-change scan;
3. a current locked-patch client measurement;
4. the verified patch and evidence references.

The absence of a later patch-note mention does not fill a cell. A globally
verified CC record must contain a verified boolean for every interaction,
including the slow-resistance auxiliary channel.
