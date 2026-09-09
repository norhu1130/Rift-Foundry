# Deterministic combat timeline semantics

## Event model

An action event owns one or more ordered outputs. Version 1 supports damage,
healing, and shielding outputs. Basic attacks and abilities use separate action
channels, while events at the same millisecond require an explicit unique
sequence number.

This ownership is deliberate: cancelling one ability event removes all of its
dependent outputs. A W-like event that deals damage and heals does not require a
new objective axis merely to make both outputs disappear when its cast is
prevented.

## Processing order

1. Sort actions by `(at_ms, sequence)`.
2. Skip a cancelled action before processing any output.
3. Skip actions whose source is dead or whose required opponent is dead.
4. Process each output in declared order.
5. Damage is mitigated, then absorbed by shield, then removes HP.
6. Healing is capped at maximum HP.
7. Shields add to the current shield pool.

All events at exactly the horizon are included in horizon metrics and state.
Events after a required opponent dies are not executed. The final damaging event
retains its full post-mitigation amount in damage metrics, while HP loss is capped
at remaining HP; both numbers are present in the audit log.

## Derived metrics

`target_dead_at_horizon` comes only from the simulated target state after every
event at or before the horizon. It is not inferred by comparing an aggregate
damage number with generic EHP.

The result separately exposes:

- post-mitigation damage to the target at the configured horizon;
- post-mitigation damage to the target over the full encounter;
- actor and target HP, shield, and death state at the horizon and encounter end;
- an ordered log containing raw damage, mitigated damage, shield absorption, HP
  delta, and state after every output.

## CC adjustment boundary

CC adjustment is a fact-gated preprocessing pass over action events. A verified
CC interval cancels only events in its declared blocked channels. Cleanse and
QSS activations may end an active interval when the corresponding interaction
is verified; an immunity window may prevent application. A post-Cleanse or
persistent tenacity effect is represented as a duration-multiplier window and
applies only to CC beginning inside that window.

The adjustment pass does not implement a tenacity stacking formula. It accepts
at most one already-resolved multiplier at a CC application instant and rejects
overlap. If the mechanic record or a required interaction is unverified, the
pass returns `UNKNOWN` with neither adjusted actions nor numeric uptime.

### Champion control-immunity windows

Champion Cogs expose discrete control immunity through
`ControlImmunityWindow`; it is not represented as 100% tenacity. Each incoming
`CastBlockWindow` carries a `ControlType`, allowing selective immunity to treat
blind, stun, slow, and other controls independently. `ControlType.ALL` is
reserved for effects such as Olaf's Ragnarok that reject every modeled control
type during a fixed interval.

An immunity window is causally linked to its enabling action. If that source
action is cancelled during fixed-point resolution, the immunity window is
absent. When immunity rejects a mixed-output spell, preprocessing removes only
the matching `StatusOutput`; damage, healing, and other sibling outputs remain
in the event. The same rule applies when the immune champion occupies either
matchup role.

Tenacity and immunity remain separate operations: tenacity shortens a
`tenacity_reducible` cast-block interval, whereas immunity prevents the control
application entirely. Neither operation changes the damage component of the
source action.

## Deferred behavior

Shield expiry, heal amplification, regeneration ticks, damage-over-time ticks,
resource costs, attack scheduling, and CC-derived cancellation are not silently
approximated. Later tasks may generate these same typed events or mark them
cancelled, but must preserve this processing contract.
