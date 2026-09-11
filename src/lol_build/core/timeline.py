"""Deterministic two-combatant event timeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)


class TimelineError(ValueError):
    """Raised when a timeline contract is invalid."""


class EntityId(StrEnum):
    """Identify one combat participant on either side of an encounter.

    ``ACTOR`` leads the side receiving the recommendation and ``TARGET`` leads
    the opposing side. Both remain the only members of their side in a duel, so
    one-versus-one encounters keep their original two-entity identifiers.
    """

    ACTOR = "ACTOR"
    ALLY_2 = "ALLY_2"
    ALLY_3 = "ALLY_3"
    ALLY_4 = "ALLY_4"
    ALLY_5 = "ALLY_5"
    TARGET = "TARGET"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    TARGET_4 = "TARGET_4"
    TARGET_5 = "TARGET_5"


ALLY_ENTITIES: tuple[EntityId, ...] = (
    EntityId.ACTOR,
    EntityId.ALLY_2,
    EntityId.ALLY_3,
    EntityId.ALLY_4,
    EntityId.ALLY_5,
)

OPPONENT_ENTITIES: tuple[EntityId, ...] = (
    EntityId.TARGET,
    EntityId.TARGET_2,
    EntityId.TARGET_3,
    EntityId.TARGET_4,
    EntityId.TARGET_5,
)


class ActionChannel(StrEnum):
    """Classify actions for crowd-control cancellation rules."""

    BASIC_ATTACK = "BASIC_ATTACK"
    ABILITY = "ABILITY"
    MOVEMENT = "MOVEMENT"
    ITEM_ACTIVE = "ITEM_ACTIVE"
    PASSIVE = "PASSIVE"


@dataclass(frozen=True)
class Combatant:
    """Provide immutable initial state for one timeline participant."""

    entity: EntityId
    max_hp: Decimal
    current_hp: Decimal
    armor: Decimal
    magic_resistance: Decimal
    shield: Decimal = Decimal(0)
    statuses: tuple[tuple[str, int], ...] = ()
    percent_armor_penetration: Decimal = Decimal(0)
    flat_armor_penetration: Decimal = Decimal(0)
    percent_magic_penetration: Decimal = Decimal(0)
    flat_magic_penetration: Decimal = Decimal(0)
    tenacity: Decimal = Decimal(0)
    life_steal: Decimal = Decimal(0)
    omnivamp: Decimal = Decimal(0)
    health_regen_per_second: Decimal = Decimal(0)


@dataclass(frozen=True)
class DamageOutput:
    """Deal fixed raw damage with optional output-scoped penetration.

    Output penetration is combined multiplicatively with the source's matching
    percentage penetration, then its flat value is added to source flat
    penetration. This keeps spell-specific armor ignore local to the damage
    event instead of mutating the attacker or later events.

    ``source_heal_ratio`` heals the source for that fraction of the damage this
    output deals, for spells such as Vladimir's Hemoplague that restore health
    equal to their own damage rather than granting a lasting vamp stat.
    """

    recipient: EntityId
    amount: Decimal
    damage_type: DamageType
    percent_resistance_penetration: Decimal = Decimal(0)
    flat_resistance_penetration: Decimal = Decimal(0)
    source_heal_ratio: Decimal = Decimal(0)


@dataclass(frozen=True)
class HealOutput:
    """Restore health to a timeline participant."""

    recipient: EntityId
    amount: Decimal


@dataclass(frozen=True)
class MissingHealthHealOutput:
    """Restore health scaled by the recipient's missing health at resolution.

    The amount is read when the event resolves, not when it is scheduled, so a
    heal such as Darius's Decimate grows with the damage taken earlier in the
    same encounter.
    """

    recipient: EntityId
    missing_health_ratio: Decimal
    base_amount: Decimal = Decimal(0)


@dataclass(frozen=True)
class HealthCostOutput:
    """Spend health without treating the payment as combat damage.

    Health costs bypass resistance, shields, incoming-damage modifiers, and
    damage aggregates. ``health_floor`` supports costs that cannot kill the
    caster.
    """

    recipient: EntityId
    flat_amount: Decimal = Decimal(0)
    current_health_ratio: Decimal = Decimal(0)
    health_floor: Decimal = Decimal(1)


@dataclass(frozen=True)
class MaxHealthModifierOutput:
    """Temporarily increase maximum and current health by one amount."""

    recipient: EntityId
    amount: Decimal
    duration_ms: int


@dataclass(frozen=True)
class ShieldOutput:
    """Grant a permanent or timed, optionally typed shield."""

    recipient: EntityId
    amount: Decimal
    duration_ms: int | None = None
    damage_types: tuple[DamageType, ...] = ()
    decay_delay_ms: int | None = None


@dataclass(frozen=True)
class CurrentHealthDamageOutput:
    """Deal damage proportional to the recipient's current health."""

    recipient: EntityId
    ratio: Decimal
    damage_type: DamageType
    cap: Decimal | None = None


@dataclass(frozen=True)
class MissingHealthDamageOutput:
    """Deal base damage plus a fraction of missing health."""

    recipient: EntityId
    base_amount: Decimal
    missing_health_ratio: Decimal
    damage_type: DamageType


@dataclass(frozen=True)
class ResistanceReductionOutput:
    """Apply a stackable, timed armor or magic-resistance reduction."""

    recipient: EntityId
    stat: str
    fraction_per_stack: Decimal
    max_stacks: int
    duration_ms: int
    state_key: str


@dataclass(frozen=True)
class StatusOutput:
    """Apply a timed status with an optional numeric magnitude."""

    recipient: EntityId
    status: str
    duration_ms: int
    magnitude: Decimal = Decimal(1)


@dataclass(frozen=True)
class RemoveStatusOutput:
    """Remove one status or a supported crowd-control group."""

    recipient: EntityId
    group: str


@dataclass(frozen=True)
class ReviveOutput:
    """Restore a dead recipient with a fixed amount of health."""

    recipient: EntityId
    health_amount: Decimal


@dataclass(frozen=True)
class StatModifierOutput:
    """Apply a permanent or timed runtime stat modifier."""

    recipient: EntityId
    stat: str
    amount: Decimal
    duration_ms: int | None = None


@dataclass(frozen=True)
class ExecuteOutput:
    """Kill a recipient at or below a health-ratio threshold."""

    recipient: EntityId
    health_ratio_threshold: Decimal


@dataclass(frozen=True)
class DeathPreventionOutput:
    """Prevent damage from reducing a recipient below a fixed health floor.

    A window with a trigger — Zilean's Chronoshift, for instance — is consumed
    the first time it actually stops lethal damage: the recipient enters
    stasis for ``trigger_stasis_ms`` and then receives ``trigger_heal``. A
    window without one simply holds the floor until it expires.
    """

    recipient: EntityId
    health_floor: Decimal
    duration_ms: int
    state_key: str
    trigger_stasis_ms: int = 0
    trigger_heal: Decimal = Decimal(0)


type EventOutput = (
    DamageOutput
    | HealOutput
    | MissingHealthHealOutput
    | HealthCostOutput
    | MaxHealthModifierOutput
    | ShieldOutput
    | CurrentHealthDamageOutput
    | MissingHealthDamageOutput
    | ResistanceReductionOutput
    | StatusOutput
    | RemoveStatusOutput
    | ReviveOutput
    | StatModifierOutput
    | ExecuteOutput
    | DeathPreventionOutput
)


@dataclass(frozen=True)
class ActionEvent:
    """Bundle atomic outputs at one deterministic timestamp and sequence."""

    id: str
    at_ms: int
    sequence: int
    source: EntityId
    channel: ActionChannel
    outputs: tuple[EventOutput, ...]
    requires_living_opponent: bool = True
    cancelled: bool = False
    cancellation_reason: str | None = None
    requires_source_alive: bool = True
    #: Event this one continues (a returning blade, a later tick, a detonation).
    #: Control that blocks new casts does not stop an already-cast spell, so a
    #: continuation is cancelled only when its origin cast is.
    origin_event_id: str | None = None


@dataclass(frozen=True)
class DamageModifierWindow:
    """Reduce selected incoming damage types during a fixed interval."""

    id: str
    start_ms: int
    end_ms: int
    recipient: EntityId
    damage_types: tuple[DamageType, ...]
    multiplier: Decimal


@dataclass(frozen=True)
class CombatantSnapshot:
    """Expose observable participant state at a timeline checkpoint."""

    current_hp: Decimal
    shield: Decimal
    dead: bool
    statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimelineLogEntry:
    """Record one applied, skipped, blocked, or cancelled output."""

    at_ms: int
    sequence: int
    event_id: str
    action_channel: ActionChannel
    operation: str
    status: str
    recipient: EntityId | None
    damage_type: DamageType | None
    raw_amount: Decimal | None
    post_mitigation_amount: Decimal | None
    shield_absorbed: Decimal | None
    hp_delta: Decimal | None
    hp_after: Decimal | None
    shield_after: Decimal | None
    detail: str | None


@dataclass(frozen=True)
class TimelineResult:
    """Contain checkpoint state, aggregate damage, and the complete event log.

    The ``target_*`` and ``damage_to_target_*`` fields describe the primary
    opponent alone, which is the whole opposing side in a duel. The mappings
    keyed by entity carry every opponent present in the encounter.
    """

    duration_ms: int
    horizon_ms: int
    actor_at_horizon: CombatantSnapshot
    target_at_horizon: CombatantSnapshot
    actor_at_end: CombatantSnapshot
    target_at_end: CombatantSnapshot
    damage_to_target_first_horizon: Decimal
    damage_to_target_total: Decimal
    target_dead_at_horizon: bool
    log: tuple[TimelineLogEntry, ...]
    targets_at_horizon: Mapping[EntityId, CombatantSnapshot] = field(default_factory=dict)
    targets_at_end: Mapping[EntityId, CombatantSnapshot] = field(default_factory=dict)
    damage_by_target_first_horizon: Mapping[EntityId, Decimal] = field(default_factory=dict)
    damage_by_target_total: Mapping[EntityId, Decimal] = field(default_factory=dict)
    allies_at_horizon: Mapping[EntityId, CombatantSnapshot] = field(default_factory=dict)
    allies_at_end: Mapping[EntityId, CombatantSnapshot] = field(default_factory=dict)
    damage_by_source_first_horizon: Mapping[EntityId, Decimal] = field(default_factory=dict)
    damage_by_source_total: Mapping[EntityId, Decimal] = field(default_factory=dict)
    death_ms_by_entity: Mapping[EntityId, int] = field(default_factory=dict)
    healing_by_entity: Mapping[EntityId, Decimal] = field(default_factory=dict)
    healing_prevented_by_entity: Mapping[EntityId, Decimal] = field(default_factory=dict)
    healing_prevented_by_source: Mapping[EntityId, Decimal] = field(default_factory=dict)

    @property
    def opposing_side_healing(self) -> Decimal:
        """Sum the health every opponent restored during the encounter.

        :return: Healing received by the opposing side after reductions.
        """
        return sum(
            (
                value
                for entity, value in self.healing_by_entity.items()
                if entity not in ALLY_ENTITIES
            ),
            Decimal(0),
        )

    @property
    def actor_healing_prevented(self) -> Decimal:
        """Report the opponent healing removed by reductions the actor applied.

        :return: Healing prevented through healing-reduction statuses sourced
            from the actor.
        """
        return self.healing_prevented_by_source.get(EntityId.ACTOR, Decimal(0))

    def survival_ms(self, entity: EntityId) -> int:
        """Report how long one participant stayed alive.

        End-of-encounter health stops separating builds once a participant dies,
        because every losing build reports zero. Survival time keeps ordering
        those builds by how much longer each one lasted.

        :param entity: Participant whose survival is required.
        :return: Millisecond of death, or the full duration if it survived.
        """
        return self.death_ms_by_entity.get(entity, self.duration_ms)

    @property
    def damage_to_all_targets_total(self) -> Decimal:
        """Sum the damage dealt to every opponent in the encounter.

        :return: Total post-mitigation damage across the opposing side.
        """
        return sum(self.damage_by_target_total.values(), Decimal(0))

    @property
    def actor_survival_ms(self) -> int:
        """Report how long the actor stayed alive.

        :return: Millisecond of the actor's death, or the full duration.
        """
        return self.survival_ms(EntityId.ACTOR)

    @property
    def actor_damage_dealt(self) -> Decimal:
        """Report the damage the actor alone dealt to the opposing side.

        Allies fight in the same timeline, so a build must be judged on what the
        actor itself removed rather than on the side's combined output.

        :return: Post-mitigation damage sourced from the actor.
        """
        return self.damage_by_source_total.get(EntityId.ACTOR, Decimal(0))

    @property
    def actor_damage_dealt_first_horizon(self) -> Decimal:
        """Report the actor's own damage inside the early measurement horizon.

        :return: Post-mitigation damage sourced from the actor before the horizon.
        """
        return self.damage_by_source_first_horizon.get(EntityId.ACTOR, Decimal(0))

    @property
    def allies_dead_at_end(self) -> int:
        """Count the actor's side members that finished the encounter dead.

        :return: Number of dead participants on the actor's side.
        """
        return sum(snapshot.dead for snapshot in self.allies_at_end.values())

    @property
    def opponents_dead_at_end(self) -> int:
        """Count opponents that finished the encounter dead.

        :return: Number of dead opponents at the end of the timeline.
        """
        return sum(snapshot.dead for snapshot in self.targets_at_end.values())


@dataclass
class _MutableCombatant:
    """Maintain internal participant state while replaying immutable events."""

    max_hp: Decimal
    current_hp: Decimal
    armor: Decimal
    magic_resistance: Decimal
    shield: Decimal
    percent_armor_penetration: Decimal = Decimal(0)
    flat_armor_penetration: Decimal = Decimal(0)
    percent_magic_penetration: Decimal = Decimal(0)
    flat_magic_penetration: Decimal = Decimal(0)
    tenacity: Decimal = Decimal(0)
    resistance_reductions: dict[str, tuple[str, Decimal, int, int]] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    status_magnitudes: dict[str, Decimal] = field(default_factory=dict)
    timed_shields: list[_TimedShield] = field(default_factory=list)
    stat_modifiers: dict[str, dict[str, tuple[Decimal, int | None]]] = field(default_factory=dict)
    death_preventions: dict[str, tuple[Decimal, int, int, Decimal]] = field(default_factory=dict)
    pending_heals: list[tuple[int, Decimal]] = field(default_factory=list)
    timed_max_health: list[tuple[Decimal, int]] = field(default_factory=list)
    life_steal: Decimal = Decimal(0)
    omnivamp: Decimal = Decimal(0)
    health_regen_per_second: Decimal = Decimal(0)
    regen_accrued_ms: int = 0
    status_sources: dict[str, EntityId] = field(default_factory=dict)

    def receive_healing(self, amount: Decimal) -> tuple[Decimal, Decimal, EntityId | None]:
        """Apply healing through healing reduction, amplification, and the health cap.

        Every restoration path — ability heals, vamp, and regeneration — goes
        through this one method, so Grievous Wounds reduces all of them the same
        way it does in the client.

        :param amount: Healing requested before reduction and amplification.
        :return: Health actually restored, healing removed by reduction, and the
            participant whose reduction status removed it (``None`` if none).
        """
        reduction = min(Decimal(1), self.status_magnitudes.get("HEALING_REDUCTION", Decimal(0)))
        amplified = amount * (
            Decimal(1) + self.stat_modifier_total("HEALING_RECEIVED_INCREASE_PERCENT")
        )
        adjusted = amplified * (Decimal(1) - reduction)
        restored = min(adjusted, max(Decimal(0), self.max_hp - self.current_hp))
        self.current_hp += restored
        # Only healing that the cap would otherwise have allowed counts as
        # prevented; reducing a heal that would overflow full health prevents
        # nothing.
        prevented = min(amplified, max(Decimal(0), self.max_hp - self.current_hp + restored))
        prevented = max(Decimal(0), prevented - restored)
        return restored, prevented, self.status_sources.get("HEALING_REDUCTION")

    def accrue_regeneration(self, to_ms: int) -> tuple[Decimal, Decimal, EntityId | None]:
        """Regenerate health continuously from the last accrual up to ``to_ms``.

        :param to_ms: Replay timestamp regeneration is brought up to.
        :return: Restored health, healing prevented by reduction, and its source.
        """
        elapsed = to_ms - self.regen_accrued_ms
        self.regen_accrued_ms = max(self.regen_accrued_ms, to_ms)
        if elapsed <= 0 or self.dead or self.health_regen_per_second <= 0:
            return Decimal(0), Decimal(0), None
        return self.receive_healing(self.health_regen_per_second * Decimal(elapsed) / Decimal(1000))

    @property
    def dead(self) -> bool:
        """Return whether health has reached zero.

        :return: ``True`` when the combatant is dead.
        """
        return self.current_hp <= 0

    def snapshot(self) -> CombatantSnapshot:
        """Freeze the current observable state.

        :return: Immutable combatant checkpoint.
        """
        return CombatantSnapshot(
            current_hp=self.current_hp,
            shield=self.shield
            + sum((timed.current_amount for timed in self.timed_shields), Decimal(0)),
            dead=self.dead,
            statuses=tuple(sorted(self.statuses)),
        )

    def expire_reductions(self, at_ms: int) -> None:
        """Discard resistance reductions expired by ``at_ms``.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        self.resistance_reductions = {
            key: value for key, value in self.resistance_reductions.items() if at_ms < value[3]
        }

    def effective_resistance(self, stat: str) -> Decimal:
        """Return resistance after active fractional reductions.

        :param stat: ``ARMOR`` or ``MAGIC_RESISTANCE``.
        :return: Effective resistance value.
        """
        base = (
            self.armor if stat == "ARMOR" else self.magic_resistance
        ) + self.stat_modifier_total(stat)
        reduction = sum(
            (
                fraction * stacks
                for stored_stat, fraction, stacks, _ in self.resistance_reductions.values()
                if stored_stat == stat
            ),
            Decimal(0),
        )
        return base * max(Decimal(0), Decimal(1) - reduction)

    def expire_statuses(self, at_ms: int) -> None:
        """Discard statuses expired by ``at_ms``.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        self.statuses = {
            status: end_ms for status, end_ms in self.statuses.items() if at_ms < end_ms
        }
        self.status_magnitudes = {
            status: magnitude
            for status, magnitude in self.status_magnitudes.items()
            if status in self.statuses
        }

    def expire_stat_modifiers(self, at_ms: int) -> None:
        """Discard runtime stat modifiers expired by ``at_ms``.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        self.stat_modifiers = {
            stat: {
                key: (amount, end_ms)
                for key, (amount, end_ms) in values.items()
                if end_ms is None or at_ms < end_ms
            }
            for stat, values in self.stat_modifiers.items()
        }
        self.stat_modifiers = {
            stat: values for stat, values in self.stat_modifiers.items() if values
        }

    def expire_death_preventions(self, at_ms: int) -> None:
        """Discard death-prevention windows expired by ``at_ms``.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        self.death_preventions = {
            key: value for key, value in self.death_preventions.items() if at_ms < value[1]
        }

    def expire_max_health(self, at_ms: int) -> None:
        """Remove expired maximum-health grants and clamp current health.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        active: list[tuple[Decimal, int]] = []
        for amount, end_ms in self.timed_max_health:
            if end_ms <= at_ms:
                self.max_hp -= amount
                self.current_hp = min(self.current_hp, self.max_hp)
            else:
                active.append((amount, end_ms))
        self.timed_max_health = active

    def active_health_floor(self) -> Decimal:
        """Return the strongest currently active health floor.

        :return: Maximum health floor across active death-prevention windows.
        """
        return max(
            (floor for floor, *_ in self.death_preventions.values()),
            default=Decimal(0),
        )

    def trigger_death_prevention(self, at_ms: int) -> str | None:
        """Consume the first triggered death-prevention window after lethal damage.

        :param at_ms: Timestamp of the damage the window stopped.
        :return: State key of the consumed window, or ``None`` if none triggers.
        """
        for key in sorted(self.death_preventions):
            _, _, stasis_ms, heal = self.death_preventions[key]
            if stasis_ms <= 0 and heal <= 0:
                continue
            del self.death_preventions[key]
            if stasis_ms > 0:
                self.statuses["STASIS"] = max(self.statuses.get("STASIS", 0), at_ms + stasis_ms)
                self.status_magnitudes["STASIS"] = Decimal(1)
            if heal > 0:
                self.pending_heals.append((at_ms + stasis_ms, heal))
            return key
        return None

    def release_pending_heals(self, to_ms: int) -> list[Decimal]:
        """Remove scheduled trigger heals due at or before ``to_ms``.

        :param to_ms: Replay timestamp heals are released up to.
        :return: Heal amounts that became due, in schedule order.
        """
        due = sorted(entry for entry in self.pending_heals if entry[0] <= to_ms)
        self.pending_heals = [entry for entry in self.pending_heals if entry[0] > to_ms]
        return [amount for _, amount in due]

    def damage_hp_loss(self, damage_after_shields: Decimal) -> tuple[Decimal, Decimal]:
        """Clamp incoming health damage against active death prevention.

        :param damage_after_shields: Post-mitigation damage not absorbed by shields.
        :return: Applied health loss and amount stopped by the active floor.
        """
        floor = min(self.max_hp, self.active_health_floor())
        maximum_loss = max(Decimal(0), self.current_hp - floor)
        hp_loss = min(maximum_loss, damage_after_shields)
        return hp_loss, damage_after_shields - hp_loss

    def stat_modifier_total(self, stat: str) -> Decimal:
        """Sum active additive modifiers for one stat.

        :param stat: Normalized stat name.
        :return: Additive modifier total.
        """
        return sum(
            (amount for amount, _ in self.stat_modifiers.get(stat, {}).values()),
            Decimal(0),
        )

    def stat_modifier_product(self, stat: str) -> Decimal:
        """Multiply active factors for one stat.

        :param stat: Normalized stat name.
        :return: Multiplicative modifier product.
        """
        result = Decimal(1)
        for amount, _ in self.stat_modifiers.get(stat, {}).values():
            result *= amount
        return result

    def effective_tenacity(self) -> Decimal:
        """Return the bounded aggregate used by the deterministic v1 CC model.

        :return: Multiplicatively combined permanent and temporary tenacity.
        """
        remaining_duration = Decimal(1) - self.tenacity
        for amount, _ in self.stat_modifiers.get("TENACITY_PERCENT", {}).values():
            remaining_duration *= Decimal(1) - amount
        return min(
            Decimal("0.99"),
            max(Decimal(0), Decimal(1) - remaining_duration),
        )

    def update_shields(self, at_ms: int) -> None:
        """Expire and decay timed shields to the current timestamp.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        active: list[_TimedShield] = []
        for timed in self.timed_shields:
            timed.decay_to(at_ms)
            if timed.current_amount > 0 and at_ms < timed.end_ms:
                active.append(timed)
        self.timed_shields = active

    def absorb_shield(self, damage: Decimal, damage_type: DamageType, at_ms: int) -> Decimal:
        """Consume compatible shields and return absorbed damage.

        :param damage: Incoming post-mitigation damage.
        :param damage_type: Incoming damage type.
        :param at_ms: Current replay timestamp.
        :return: Amount absorbed by shields.
        """
        self.update_shields(at_ms)
        absorbed = min(self.shield, damage)
        self.shield -= absorbed
        remaining = damage - absorbed
        for timed in self.timed_shields:
            if remaining <= 0:
                break
            if timed.damage_types and damage_type not in timed.damage_types:
                continue
            consumed = min(timed.current_amount, remaining)
            timed.current_amount -= consumed
            remaining -= consumed
            absorbed += consumed
        return absorbed


@dataclass
class _TimedShield:
    """Track the remaining value and optional linear decay of one shield."""

    initial_amount: Decimal
    current_amount: Decimal
    start_ms: int
    end_ms: int
    decay_start_ms: int | None
    damage_types: tuple[DamageType, ...]

    def decay_to(self, at_ms: int) -> None:
        """Advance this shield's linear decay state.

        :param at_ms: Current replay timestamp.
        :return: None.
        """
        if self.decay_start_ms is None or at_ms <= self.decay_start_ms:
            return
        if at_ms >= self.end_ms:
            self.current_amount = Decimal(0)
            return
        duration = Decimal(self.end_ms - self.decay_start_ms)
        remaining = Decimal(self.end_ms - at_ms) / duration
        self.current_amount = min(self.current_amount, self.initial_amount * remaining)


def opponent_sequence_offset(entity: EntityId) -> int:
    """Return the sequence block reserved for one opponent beyond the primary.

    Sequence numbers break ties between events sharing a timestamp, so every
    participant needs a disjoint block. The actor and the primary target keep
    offset zero, which leaves duel sequence numbers exactly as they were, and
    each further opponent reserves its own block above them.

    :param entity: Participant whose sequence block is required.
    :return: Offset added to a participant's base sequence number.
    """
    if entity in ALLY_ENTITIES:
        return 1_000_000 * ALLY_ENTITIES.index(entity)
    return 100_000 * OPPONENT_ENTITIES.index(entity)


def _finite_decimal(value: Decimal, *, name: str) -> None:
    """Require a finite Decimal input.

    :param value: Decimal to validate.
    :param name: Human-readable error label.
    :return: None.
    :raises TimelineError: If the value is non-finite.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise TimelineError(f"{name} must be finite")


def _validate_combatant(combatant: Combatant) -> None:
    """Validate initial combatant invariants.

    :param combatant: Initial state to validate.
    :return: None.
    :raises TimelineError: If health, defenses, or statuses are invalid.
    """
    if not isinstance(combatant, Combatant):
        raise TypeError("combatants must be Combatant")
    for name in ("max_hp", "current_hp", "armor", "magic_resistance", "shield"):
        _finite_decimal(getattr(combatant, name), name=f"{combatant.entity}.{name}")
    if combatant.max_hp <= 0:
        raise TimelineError(f"{combatant.entity}.max_hp must be positive")
    if not Decimal(0) <= combatant.current_hp <= combatant.max_hp:
        raise TimelineError(f"{combatant.entity}.current_hp must be within [0, max_hp]")
    if combatant.shield < 0:
        raise TimelineError(f"{combatant.entity}.shield must be non-negative")


def _validate_event(event: ActionEvent, *, duration_ms: int) -> None:
    """Validate one event and every contained output.

    :param event: Event contract to validate.
    :param duration_ms: Inclusive timeline duration bound.
    :return: None.
    :raises TimelineError: If ordering, timing, or output data is invalid.
    """
    if not event.id:
        raise TimelineError("event id must not be empty")
    if isinstance(event.at_ms, bool) or not isinstance(event.at_ms, int):
        raise TypeError("event at_ms must be int")
    if isinstance(event.sequence, bool) or not isinstance(event.sequence, int):
        raise TypeError("event sequence must be int")
    if not 0 <= event.at_ms <= duration_ms:
        raise TimelineError(f"event {event.id!r} is outside the timeline")
    if event.cancelled and not event.cancellation_reason:
        raise TimelineError(f"cancelled event {event.id!r} requires a reason")
    if not event.cancelled and event.cancellation_reason is not None:
        raise TimelineError(f"active event {event.id!r} cannot have a cancellation reason")
    if not event.outputs:
        raise TimelineError(f"event {event.id!r} must have at least one output")
    for index, output in enumerate(event.outputs):
        if isinstance(output, MissingHealthHealOutput):
            _finite_decimal(
                output.missing_health_ratio,
                name=f"event {event.id}.outputs[{index}].missing_health_ratio",
            )
            _finite_decimal(output.base_amount, name=f"event {event.id}.outputs[{index}].base")
            if not Decimal(0) <= output.missing_health_ratio <= Decimal(1):
                raise TimelineError("missing-health heal ratio must be within [0, 1]")
            if output.base_amount < 0:
                raise TimelineError("missing-health heal base amount must be non-negative")
        if isinstance(output, (DamageOutput, HealOutput, ShieldOutput)):
            _finite_decimal(output.amount, name=f"event {event.id}.outputs[{index}].amount")
            if output.amount < 0:
                raise TimelineError(f"event {event.id!r} output amount must be non-negative")
            if isinstance(output, DamageOutput):
                _finite_decimal(
                    output.percent_resistance_penetration,
                    name=(f"event {event.id}.outputs[{index}].percent_resistance_penetration"),
                )
                _finite_decimal(
                    output.flat_resistance_penetration,
                    name=(f"event {event.id}.outputs[{index}].flat_resistance_penetration"),
                )
                if not Decimal(0) <= output.percent_resistance_penetration <= Decimal(1):
                    raise TimelineError("damage-output percent penetration must be within [0, 1]")
                if output.flat_resistance_penetration < 0:
                    raise TimelineError("damage-output flat penetration must be non-negative")
                _finite_decimal(
                    output.source_heal_ratio,
                    name=f"event {event.id}.outputs[{index}].source_heal_ratio",
                )
                if output.source_heal_ratio < 0:
                    raise TimelineError("damage-output source heal ratio must be non-negative")
                if output.damage_type is DamageType.TRUE and (
                    output.percent_resistance_penetration or output.flat_resistance_penetration
                ):
                    raise TimelineError("true damage cannot declare resistance penetration")
            if isinstance(output, ShieldOutput):
                if output.duration_ms is not None and output.duration_ms <= 0:
                    raise TimelineError("shield duration must be positive")
                if len(set(output.damage_types)) != len(output.damage_types):
                    raise TimelineError("shield damage types must be unique")
                if output.decay_delay_ms is not None and output.duration_ms is None:
                    raise TimelineError("decaying shield requires duration")
        elif isinstance(output, CurrentHealthDamageOutput):
            _finite_decimal(output.ratio, name=f"event {event.id}.outputs[{index}].ratio")
            if not Decimal(0) <= output.ratio <= Decimal(1):
                raise TimelineError("current-health damage ratio must be within [0, 1]")
            if output.cap is not None:
                _finite_decimal(output.cap, name=f"event {event.id}.outputs[{index}].cap")
                if output.cap < 0:
                    raise TimelineError("current-health damage cap must be non-negative")
        elif isinstance(output, HealthCostOutput):
            _finite_decimal(output.flat_amount, name="health cost flat amount")
            _finite_decimal(output.current_health_ratio, name="health cost ratio")
            _finite_decimal(output.health_floor, name="health cost floor")
            if output.flat_amount < 0:
                raise TimelineError("health cost flat amount must be non-negative")
            if not Decimal(0) <= output.current_health_ratio <= Decimal(1):
                raise TimelineError("health cost ratio must be within [0, 1]")
            if output.health_floor < 0:
                raise TimelineError("health cost floor must be non-negative")
            if not output.flat_amount and not output.current_health_ratio:
                raise TimelineError("health cost requires a positive amount or ratio")
        elif isinstance(output, MaxHealthModifierOutput):
            _finite_decimal(output.amount, name="maximum-health modifier amount")
            if output.amount <= 0:
                raise TimelineError("maximum-health modifier amount must be positive")
            if output.duration_ms <= 0:
                raise TimelineError("maximum-health modifier duration must be positive")
        elif isinstance(output, MissingHealthDamageOutput):
            _finite_decimal(output.base_amount, name="missing-health damage base amount")
            _finite_decimal(output.missing_health_ratio, name="missing-health damage ratio")
            if output.base_amount < 0:
                raise TimelineError("missing-health damage base amount must be non-negative")
            if not Decimal(0) <= output.missing_health_ratio <= Decimal(1):
                raise TimelineError("missing-health damage ratio must be within [0, 1]")
        elif isinstance(output, ResistanceReductionOutput):
            _finite_decimal(
                output.fraction_per_stack,
                name=f"event {event.id}.outputs[{index}].fraction_per_stack",
            )
            if output.stat not in {"ARMOR", "MAGIC_RESISTANCE"}:
                raise TimelineError("resistance reduction stat is invalid")
            if not Decimal(0) <= output.fraction_per_stack <= Decimal(1):
                raise TimelineError("resistance reduction fraction must be within [0, 1]")
            if output.max_stacks <= 0 or output.duration_ms <= 0 or not output.state_key:
                raise TimelineError("resistance reduction state contract is invalid")
        elif isinstance(output, StatusOutput):
            if not output.status or output.duration_ms <= 0:
                raise TimelineError("status output contract is invalid")
            _finite_decimal(
                output.magnitude,
                name=f"event {event.id}.outputs[{index}].magnitude",
            )
            if output.magnitude < 0:
                raise TimelineError("status magnitude must be non-negative")
        elif isinstance(output, RemoveStatusOutput):
            if not output.group:
                raise TimelineError("remove-status output group must not be empty")
        elif isinstance(output, ReviveOutput):
            _finite_decimal(
                output.health_amount,
                name=f"event {event.id}.outputs[{index}].health_amount",
            )
            if output.health_amount <= 0:
                raise TimelineError("revive health must be positive")
        elif isinstance(output, StatModifierOutput):
            if not output.stat:
                raise TimelineError("stat modifier requires a stat")
            _finite_decimal(
                output.amount,
                name=f"event {event.id}.outputs[{index}].amount",
            )
            if output.duration_ms is not None and output.duration_ms <= 0:
                raise TimelineError("stat modifier duration must be positive")
        elif isinstance(output, ExecuteOutput):
            _finite_decimal(
                output.health_ratio_threshold,
                name=f"event {event.id}.outputs[{index}].health_ratio_threshold",
            )
            if not Decimal(0) <= output.health_ratio_threshold <= Decimal(1):
                raise TimelineError("execute threshold must be within [0, 1]")
        elif isinstance(output, DeathPreventionOutput):
            _finite_decimal(
                output.health_floor,
                name=f"event {event.id}.outputs[{index}].health_floor",
            )
            if output.health_floor < 0:
                raise TimelineError("death-prevention health floor must be non-negative")
            _finite_decimal(
                output.trigger_heal,
                name=f"event {event.id}.outputs[{index}].trigger_heal",
            )
            if output.trigger_stasis_ms < 0 or output.trigger_heal < 0:
                raise TimelineError("death-prevention trigger must be non-negative")
            if output.duration_ms <= 0 or not output.state_key:
                raise TimelineError("death-prevention window contract is invalid")


def _opposing(entity: EntityId) -> tuple[EntityId, ...]:
    """Return every participant on the side opposite ``entity``.

    A duel yields exactly one opposing entity on each side, so this reproduces
    the original two-entity pairing when no additional targets are present.

    :param entity: Current participant identifier.
    :return: Opposing participant identifiers in canonical order.
    """
    if entity in ALLY_ENTITIES:
        return OPPONENT_ENTITIES
    return ALLY_ENTITIES


def _action_log(event: ActionEvent, *, status: str, detail: str) -> TimelineLogEntry:
    """Create a zero-delta log entry for an action-level decision.

    :param event: Source action.
    :param status: Applied, skipped, blocked, or cancelled status.
    :param detail: Human-readable causal detail.
    :return: Timeline log entry.
    """
    return TimelineLogEntry(
        at_ms=event.at_ms,
        sequence=event.sequence,
        event_id=event.id,
        action_channel=event.channel,
        operation="ACTION",
        status=status,
        recipient=None,
        damage_type=None,
        raw_amount=None,
        post_mitigation_amount=None,
        shield_absorbed=None,
        hp_delta=None,
        hp_after=None,
        shield_after=None,
        detail=detail,
    )


def simulate_timeline(
    *,
    duration_ms: int,
    horizon_ms: int,
    actor: Combatant,
    target: Combatant,
    additional_allies: tuple[Combatant, ...] = (),
    additional_targets: tuple[Combatant, ...] = (),
    events: tuple[ActionEvent, ...],
    damage_modifier_windows: tuple[DamageModifierWindow, ...] = (),
) -> TimelineResult:
    """Run events in ``(at_ms, sequence)`` order and retain an audit log.

    :param duration_ms: Inclusive encounter duration in milliseconds.
    :param horizon_ms: Early-damage checkpoint in milliseconds.
    :param actor: Initial state for the actor entity.
    :param target: Initial state for the primary target entity.
    :param additional_allies: Further allies bound to ``ALLY_2`` onward.
    :param additional_targets: Further opponents bound to ``TARGET_2`` onward.
    :param events: Immutable actions from every participant and their items.
    :param damage_modifier_windows: Timed incoming-damage multipliers.
    :return: Final/checkpoint snapshots, aggregate damage, and audit entries.
    :raises TimelineError: If any combatant, event, or interval is invalid.
    """
    for name, value in (("duration_ms", duration_ms), ("horizon_ms", horizon_ms)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be int")
    if duration_ms <= 0:
        raise TimelineError("duration_ms must be positive")
    if not 0 <= horizon_ms <= duration_ms:
        raise TimelineError("horizon_ms must be within the timeline")
    _validate_combatant(actor)
    _validate_combatant(target)
    for extra in (*additional_allies, *additional_targets):
        _validate_combatant(extra)
    if actor.entity is not EntityId.ACTOR or target.entity is not EntityId.TARGET:
        raise TimelineError("actor and target must use their matching entity IDs")
    if len(additional_targets) > len(OPPONENT_ENTITIES) - 1:
        raise TimelineError("an encounter supports at most five opponents")
    expected_extra = OPPONENT_ENTITIES[1 : 1 + len(additional_targets)]
    if tuple(extra.entity for extra in additional_targets) != expected_extra:
        raise TimelineError("additional targets must use TARGET_2 onward in order")
    if len(additional_allies) > len(ALLY_ENTITIES) - 1:
        raise TimelineError("a side supports at most five participants")
    expected_allies = ALLY_ENTITIES[1 : 1 + len(additional_allies)]
    if tuple(extra.entity for extra in additional_allies) != expected_allies:
        raise TimelineError("additional allies must use ALLY_2 onward in order")

    seen_order_keys: set[tuple[int, int]] = set()
    for event in events:
        _validate_event(event, duration_ms=duration_ms)
        order_key = (event.at_ms, event.sequence)
        if order_key in seen_order_keys:
            raise TimelineError(f"duplicate event order key {order_key}")
        seen_order_keys.add(order_key)
    for window in damage_modifier_windows:
        if not window.id or not 0 <= window.start_ms < window.end_ms <= duration_ms:
            raise TimelineError("damage modifier window is invalid or outside the timeline")
        _finite_decimal(window.multiplier, name=f"window {window.id}.multiplier")
        if not Decimal(0) <= window.multiplier <= Decimal(1):
            raise TimelineError("damage modifier multiplier must be within [0, 1]")
        if not window.damage_types or len(set(window.damage_types)) != len(window.damage_types):
            raise TimelineError("damage modifier window needs unique damage types")

    def _mutable(combatant: Combatant) -> _MutableCombatant:
        """Create the mutable working state for one validated combatant.

        :param combatant: Immutable initial state for one participant.
        :return: Mutable state seeded with that participant's values.
        """
        return _MutableCombatant(
            combatant.max_hp,
            combatant.current_hp,
            combatant.armor,
            combatant.magic_resistance,
            combatant.shield,
            combatant.percent_armor_penetration,
            combatant.flat_armor_penetration,
            combatant.percent_magic_penetration,
            combatant.flat_magic_penetration,
            combatant.tenacity,
            statuses=dict(combatant.statuses),
            status_magnitudes={status: Decimal(1) for status, _ in combatant.statuses},
            life_steal=combatant.life_steal,
            omnivamp=combatant.omnivamp,
            health_regen_per_second=combatant.health_regen_per_second,
        )

    states = {
        combatant.entity: _mutable(combatant)
        for combatant in (actor, *additional_allies, target, *additional_targets)
    }
    horizon_snapshots = {entity: state.snapshot() for entity, state in states.items()}
    damage_by_target = {entity: Decimal(0) for entity in states if entity not in ALLY_ENTITIES}
    horizon_damage_by_target = dict.fromkeys(damage_by_target, Decimal(0))
    damage_by_source = dict.fromkeys(states, Decimal(0))
    death_ms_by_entity: dict[EntityId, int] = {}
    horizon_damage_by_source = dict.fromkeys(states, Decimal(0))
    healing_by_entity = dict.fromkeys(states, Decimal(0))
    healing_prevented_by_entity = dict.fromkeys(states, Decimal(0))
    healing_prevented_by_source = dict.fromkeys(states, Decimal(0))
    log: list[TimelineLogEntry] = []

    def record_healing(
        entity: EntityId,
        outcome: tuple[Decimal, Decimal, EntityId | None],
    ) -> None:
        """Accumulate restored and prevented healing for one recipient.

        :param entity: Participant that received the healing.
        :param outcome: Restored amount, prevented amount, and reduction source.
        :return: None.
        """
        restored, prevented, reducer = outcome
        healing_by_entity[entity] += restored
        healing_prevented_by_entity[entity] += prevented
        if reducer is not None and prevented > 0:
            healing_prevented_by_source[reducer] += prevented

    def accrue_all_regeneration(to_ms: int) -> None:
        """Bring every participant's passive regeneration up to ``to_ms``.

        Regeneration accrues before statuses expire at the same timestamp, so a
        healing reduction active through the elapsed interval still applies.

        :param to_ms: Replay timestamp to accrue regeneration to.
        :return: None.
        """
        for entity, state in states.items():
            record_healing(entity, state.accrue_regeneration(to_ms))
            for amount in state.release_pending_heals(to_ms):
                if not state.dead:
                    record_healing(entity, state.receive_healing(amount))

    for event in sorted(events, key=lambda item: (item.at_ms, item.sequence)):
        accrue_all_regeneration(event.at_ms)
        for state in states.values():
            state.expire_reductions(event.at_ms)
            state.expire_statuses(event.at_ms)
            state.update_shields(event.at_ms)
            state.expire_stat_modifiers(event.at_ms)
            state.expire_death_preventions(event.at_ms)
            state.expire_max_health(event.at_ms)
        source = states[event.source]
        opposing = [states[entity] for entity in _opposing(event.source) if entity in states]
        if event.cancelled:
            log.append(
                _action_log(
                    event,
                    status="CANCELLED",
                    detail=event.cancellation_reason or "unknown cancellation",
                )
            )
            continue
        if source.dead and event.requires_source_alive:
            log.append(_action_log(event, status="SKIPPED_SOURCE_DEAD", detail="source is dead"))
            continue
        if "STASIS" in source.statuses:
            log.append(
                _action_log(event, status="SKIPPED_SOURCE_STASIS", detail="source is in stasis")
            )
            continue
        if event.requires_living_opponent and all(state.dead for state in opposing):
            log.append(
                _action_log(
                    event,
                    status="SKIPPED_OPPONENT_DEAD",
                    detail="required opponent is dead",
                )
            )
            continue

        spell_shield_blocked = {
            output.recipient
            for output in event.outputs
            if (
                event.channel is ActionChannel.ABILITY
                and output.recipient is not event.source
                and "SPELL_SHIELD" in states[output.recipient].statuses
            )
        }
        for entity in spell_shield_blocked:
            states[entity].statuses.pop("SPELL_SHIELD", None)
            states[entity].status_magnitudes.pop("SPELL_SHIELD", None)
            # A companion SPELL_SHIELD_HEAL status (Sivir's Spell Shield) heals
            # its magnitude only when the shield actually blocks an ability.
            if "SPELL_SHIELD_HEAL" in states[entity].statuses:
                heal = states[entity].status_magnitudes.get("SPELL_SHIELD_HEAL", Decimal(0))
                states[entity].statuses.pop("SPELL_SHIELD_HEAL", None)
                states[entity].status_magnitudes.pop("SPELL_SHIELD_HEAL", None)
                if heal > 0:
                    record_healing(entity, states[entity].receive_healing(heal))

        for output in event.outputs:
            recipient = states[output.recipient]
            if output.recipient in spell_shield_blocked:
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        type(output).__name__.removesuffix("Output").upper(),
                        "BLOCKED_SPELL_SHIELD",
                        output.recipient,
                        output.damage_type
                        if isinstance(
                            output,
                            (DamageOutput, CurrentHealthDamageOutput, MissingHealthDamageOutput),
                        )
                        else None,
                        output.amount
                        if isinstance(output, (DamageOutput, HealOutput, ShieldOutput))
                        else None,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        "spell shield consumed",
                    )
                )
                continue
            if recipient.dead and not isinstance(output, ReviveOutput):
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        type(output).__name__.removesuffix("Output").upper(),
                        "SKIPPED_RECIPIENT_DEAD",
                        output.recipient,
                        output.damage_type
                        if isinstance(
                            output,
                            (DamageOutput, CurrentHealthDamageOutput, MissingHealthDamageOutput),
                        )
                        else None,
                        output.amount
                        if isinstance(output, (DamageOutput, HealOutput, ShieldOutput))
                        else None,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        "recipient is dead",
                    )
                )
                continue

            if isinstance(output, ReviveOutput):
                recipient.current_hp = min(recipient.max_hp, output.health_amount)
                recipient.shield = Decimal(0)
                recipient.timed_shields.clear()
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "REVIVE",
                        "APPLIED",
                        output.recipient,
                        None,
                        output.health_amount,
                        None,
                        None,
                        output.health_amount,
                        recipient.current_hp,
                        Decimal(0),
                        None,
                    )
                )
            elif isinstance(output, HealthCostOutput):
                requested = output.flat_amount + output.current_health_ratio * recipient.current_hp
                paid = min(
                    requested,
                    max(Decimal(0), recipient.current_hp - output.health_floor),
                )
                recipient.current_hp -= paid
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "HEALTH_COST",
                        "APPLIED",
                        output.recipient,
                        None,
                        requested,
                        None,
                        Decimal(0),
                        -paid,
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"health_floor:{output.health_floor}",
                    )
                )
            elif isinstance(output, MaxHealthModifierOutput):
                recipient.max_hp += output.amount
                recipient.current_hp += output.amount
                recipient.timed_max_health.append((output.amount, event.at_ms + output.duration_ms))
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "MAX_HEALTH_MODIFIER",
                        "APPLIED",
                        output.recipient,
                        None,
                        output.amount,
                        None,
                        None,
                        output.amount,
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"duration_ms:{output.duration_ms}",
                    )
                )
            elif isinstance(
                output,
                (DamageOutput, CurrentHealthDamageOutput, MissingHealthDamageOutput),
            ):
                if "STASIS" in recipient.statuses:
                    log.append(
                        TimelineLogEntry(
                            event.at_ms,
                            event.sequence,
                            event.id,
                            event.channel,
                            "DAMAGE",
                            "IMMUNE_STASIS",
                            output.recipient,
                            output.damage_type,
                            output.amount if isinstance(output, DamageOutput) else None,
                            Decimal(0),
                            Decimal(0),
                            Decimal(0),
                            recipient.current_hp,
                            recipient.shield,
                            "recipient is in stasis",
                        )
                    )
                    continue
                if isinstance(output, DamageOutput):
                    raw_amount = output.amount
                elif isinstance(output, CurrentHealthDamageOutput):
                    raw_amount = output.ratio * recipient.current_hp
                else:
                    raw_amount = output.base_amount + output.missing_health_ratio * (
                        recipient.max_hp - recipient.current_hp
                    )
                if isinstance(output, CurrentHealthDamageOutput) and output.cap is not None:
                    raw_amount = min(raw_amount, output.cap)
                if event.channel is ActionChannel.BASIC_ATTACK:
                    raw_amount *= recipient.stat_modifier_product("BASIC_ATTACK_DAMAGE_MULTIPLIER")
                raw_amount *= recipient.stat_modifier_product("CHAMPION_DAMAGE_MULTIPLIER")
                raw_amount *= Decimal(1) + recipient.stat_modifier_total(
                    "DAMAGE_TAKEN_INCREASE_PERCENT"
                )
                if output.damage_type is DamageType.MAGIC:
                    raw_amount *= Decimal(1) + recipient.stat_modifier_total(
                        "MAGIC_DAMAGE_TAKEN_INCREASE_PERCENT"
                    )
                raw_amount *= Decimal(1) + source.stat_modifier_total(
                    "DAMAGE_DEALT_INCREASE_PERCENT"
                )
                if event.channel is ActionChannel.ABILITY:
                    raw_amount *= Decimal(1) + source.stat_modifier_total(
                        "ABILITY_AND_PASSIVE_DAMAGE_INCREASE_PERCENT"
                    )
                for window in damage_modifier_windows:
                    if (
                        window.recipient is output.recipient
                        and window.start_ms <= event.at_ms < window.end_ms
                        and output.damage_type in window.damage_types
                    ):
                        raw_amount *= window.multiplier
                effective_armor = recipient.effective_resistance("ARMOR")
                effective_magic_resistance = recipient.effective_resistance("MAGIC_RESISTANCE")
                if output.damage_type is DamageType.PHYSICAL:
                    output_percent_penetration = (
                        output.percent_resistance_penetration
                        if isinstance(output, DamageOutput)
                        else Decimal(0)
                    )
                    output_flat_penetration = (
                        output.flat_resistance_penetration
                        if isinstance(output, DamageOutput)
                        else Decimal(0)
                    )
                    effective_armor = apply_resistance_pipeline(
                        effective_armor,
                        ResistanceModifiers(
                            percent_penetration=Decimal(1)
                            - (Decimal(1) - source.percent_armor_penetration)
                            * (Decimal(1) - output_percent_penetration),
                            flat_penetration=(
                                source.flat_armor_penetration + output_flat_penetration
                            ),
                        ),
                    ).effective_resistance
                elif output.damage_type is DamageType.MAGIC:
                    output_percent_penetration = (
                        output.percent_resistance_penetration
                        if isinstance(output, DamageOutput)
                        else Decimal(0)
                    )
                    output_flat_penetration = (
                        output.flat_resistance_penetration
                        if isinstance(output, DamageOutput)
                        else Decimal(0)
                    )
                    effective_magic_resistance = apply_resistance_pipeline(
                        effective_magic_resistance,
                        ResistanceModifiers(
                            percent_penetration=Decimal(1)
                            - (Decimal(1) - source.percent_magic_penetration)
                            * (Decimal(1) - output_percent_penetration),
                            flat_penetration=(
                                source.flat_magic_penetration + output_flat_penetration
                            ),
                        ),
                    ).effective_resistance
                damage = apply_resistance(
                    raw_amount,
                    output.damage_type,
                    armor=effective_armor,
                    magic_resistance=effective_magic_resistance,
                ).post_mitigation_damage
                shield_absorbed = recipient.absorb_shield(damage, output.damage_type, event.at_ms)
                hp_loss, prevented = recipient.damage_hp_loss(damage - shield_absorbed)
                recipient.current_hp -= hp_loss
                if prevented > 0:
                    recipient.trigger_death_prevention(event.at_ms)
                if output.recipient not in ALLY_ENTITIES:
                    damage_by_target[output.recipient] += damage
                    if event.at_ms <= horizon_ms:
                        horizon_damage_by_target[output.recipient] += damage
                    damage_by_source[event.source] += damage
                    if event.at_ms <= horizon_ms:
                        horizon_damage_by_source[event.source] += damage
                # Life steal heals from basic-attack damage and omnivamp from all
                # damage, both measured before shields absorb it, as in the client.
                vamp_ratio = source.omnivamp + source.stat_modifier_total("OMNIVAMP")
                if event.channel is ActionChannel.BASIC_ATTACK:
                    vamp_ratio += source.life_steal + source.stat_modifier_total("LIFESTEAL")
                # Ability vamp (Morgana's Soul Siphon, Lee Sin's Iron Will) heals
                # from champion ability and passive damage. Item effects resolve on
                # the ITEM_ACTIVE channel and are excluded.
                if event.channel in (ActionChannel.ABILITY, ActionChannel.PASSIVE):
                    vamp_ratio += source.stat_modifier_total("ABILITY_VAMP")
                if isinstance(output, DamageOutput):
                    vamp_ratio += output.source_heal_ratio
                if (
                    vamp_ratio > 0
                    and damage > 0
                    and output.recipient is not event.source
                    and not source.dead
                ):
                    vamp = source.receive_healing(damage * vamp_ratio)
                    record_healing(event.source, vamp)
                    log.append(
                        TimelineLogEntry(
                            event.at_ms,
                            event.sequence,
                            event.id,
                            event.channel,
                            "VAMP_HEAL",
                            "APPLIED",
                            event.source,
                            None,
                            damage * vamp_ratio,
                            None,
                            None,
                            vamp[0],
                            source.current_hp,
                            source.snapshot().shield,
                            f"vamp_ratio:{vamp_ratio}"
                            + (f":prevented={vamp[1]}" if vamp[1] else ""),
                        )
                    )
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "DAMAGE",
                        "APPLIED",
                        output.recipient,
                        output.damage_type,
                        raw_amount,
                        damage,
                        shield_absorbed,
                        -hp_loss,
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        (f"death_prevention_absorbed:{prevented}" if prevented > 0 else None),
                    )
                )
            elif isinstance(output, ResistanceReductionOutput):
                previous = recipient.resistance_reductions.get(output.state_key)
                stacks = min(output.max_stacks, (previous[2] if previous else 0) + 1)
                recipient.resistance_reductions[output.state_key] = (
                    output.stat,
                    output.fraction_per_stack,
                    stacks,
                    event.at_ms + output.duration_ms,
                )
                total_fraction = output.fraction_per_stack * stacks
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "RESISTANCE_REDUCTION",
                        "APPLIED",
                        output.recipient,
                        None,
                        total_fraction,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"{output.state_key}:{stacks}/{output.max_stacks}",
                    )
                )
            elif isinstance(output, StatusOutput):
                magnitude = output.magnitude
                adjusted_duration_ms = output.duration_ms
                tenacity_reducible = {
                    "SILENCE",
                    "CC_BLIND",
                    "CC_CHARM",
                    "CC_FEAR",
                    "CC_ROOT",
                    "CC_SILENCE",
                    "CC_SLOW",
                    "CC_STUN",
                    "CC_TAUNT",
                }
                if output.status in tenacity_reducible:
                    adjusted_duration_ms = max(
                        1,
                        int(
                            Decimal(output.duration_ms)
                            * (Decimal(1) - recipient.effective_tenacity())
                        ),
                    )
                if output.status == "CC_SLOW":
                    slow_resistance = recipient.stat_modifier_total("SLOW_RESISTANCE_PERCENT")
                    magnitude *= max(Decimal(0), Decimal(1) - slow_resistance)
                if (
                    output.status == "HEALING_REDUCTION"
                    and output.status in recipient.statuses
                    and recipient.status_magnitudes.get(output.status, Decimal(0)) > magnitude
                ):
                    # Grievous Wounds does not stack: a weaker application
                    # refreshes the duration but keeps the stronger reduction
                    # and its original source.
                    magnitude = recipient.status_magnitudes[output.status]
                else:
                    recipient.status_sources[output.status] = event.source
                recipient.statuses[output.status] = max(
                    event.at_ms + adjusted_duration_ms,
                    recipient.statuses.get(output.status, 0)
                    if output.status == "HEALING_REDUCTION"
                    else 0,
                )
                recipient.status_magnitudes[output.status] = magnitude
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "STATUS",
                        "APPLIED",
                        output.recipient,
                        None,
                        None,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        (
                            f"{output.status}:{event.at_ms + adjusted_duration_ms}"
                            f":magnitude={magnitude}"
                        ),
                    )
                )
            elif isinstance(output, RemoveStatusOutput):
                if output.group.startswith("CROWD_CONTROL_EXCEPT_"):
                    exclusions = {
                        f"CC_{name}"
                        for name in output.group.removeprefix("CROWD_CONTROL_EXCEPT_").split(
                            "_AND_"
                        )
                    }
                    removed = tuple(
                        sorted(
                            status
                            for status in recipient.statuses
                            if status.startswith("CC_") and status not in exclusions
                        )
                    )
                else:
                    removed = (output.group,) if output.group in recipient.statuses else ()
                for status in removed:
                    recipient.statuses.pop(status, None)
                    recipient.status_magnitudes.pop(status, None)
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "REMOVE_STATUS",
                        "APPLIED",
                        output.recipient,
                        None,
                        None,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        ",".join(removed),
                    )
                )
            elif isinstance(output, (HealOutput, MissingHealthHealOutput)):
                reduction = recipient.status_magnitudes.get("HEALING_REDUCTION", Decimal(0))
                requested = (
                    output.amount
                    if isinstance(output, HealOutput)
                    else output.base_amount
                    + output.missing_health_ratio
                    * max(Decimal(0), recipient.max_hp - recipient.current_hp)
                )
                outcome = recipient.receive_healing(requested)
                record_healing(output.recipient, outcome)
                healing = outcome[0]
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "HEAL",
                        "APPLIED",
                        output.recipient,
                        None,
                        requested,
                        None,
                        None,
                        healing,
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"healing_reduction:{reduction}" if reduction else None,
                    )
                )
            elif isinstance(output, ShieldOutput):
                received_increase = recipient.stat_modifier_total(
                    "SHIELD_RECEIVED_INCREASE_PERCENT"
                )
                shield_amount = output.amount * (Decimal(1) + received_increase)
                if output.duration_ms is None:
                    recipient.shield += shield_amount
                else:
                    recipient.timed_shields.append(
                        _TimedShield(
                            shield_amount,
                            shield_amount,
                            event.at_ms,
                            event.at_ms + output.duration_ms,
                            event.at_ms + output.decay_delay_ms
                            if output.decay_delay_ms is not None
                            else None,
                            output.damage_types,
                        )
                    )
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "SHIELD",
                        "APPLIED",
                        output.recipient,
                        None,
                        output.amount,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        None,
                    )
                )
            elif isinstance(output, StatModifierOutput):
                end_ms = (
                    event.at_ms + output.duration_ms if output.duration_ms is not None else None
                )
                recipient.stat_modifiers.setdefault(output.stat, {})[event.id] = (
                    output.amount,
                    end_ms,
                )
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "STAT_MODIFIER",
                        "APPLIED",
                        output.recipient,
                        None,
                        output.amount,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"{output.stat}:{end_ms}",
                    )
                )
            elif isinstance(output, ExecuteOutput):
                threshold_met = (
                    recipient.current_hp / recipient.max_hp <= output.health_ratio_threshold
                )
                hp_loss, prevented = (
                    recipient.damage_hp_loss(recipient.current_hp)
                    if threshold_met
                    else (Decimal(0), Decimal(0))
                )
                recipient.current_hp -= hp_loss
                if prevented > 0:
                    recipient.trigger_death_prevention(event.at_ms)
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "EXECUTE",
                        "APPLIED" if threshold_met else "THRESHOLD_NOT_MET",
                        output.recipient,
                        None,
                        output.health_ratio_threshold,
                        None,
                        None,
                        -hp_loss,
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        (f"death_prevention_absorbed:{prevented}" if prevented > 0 else None),
                    )
                )
            elif isinstance(output, DeathPreventionOutput):
                recipient.death_preventions[output.state_key] = (
                    output.health_floor,
                    event.at_ms + output.duration_ms,
                    output.trigger_stasis_ms,
                    output.trigger_heal,
                )
                log.append(
                    TimelineLogEntry(
                        event.at_ms,
                        event.sequence,
                        event.id,
                        event.channel,
                        "DEATH_PREVENTION",
                        "APPLIED",
                        output.recipient,
                        None,
                        output.health_floor,
                        None,
                        None,
                        Decimal(0),
                        recipient.current_hp,
                        recipient.snapshot().shield,
                        f"{output.state_key}:{event.at_ms + output.duration_ms}",
                    )
                )

        for entity, state in states.items():
            if state.dead and entity not in death_ms_by_entity:
                death_ms_by_entity[entity] = event.at_ms
        if event.at_ms <= horizon_ms:
            horizon_snapshots = {entity: state.snapshot() for entity, state in states.items()}

    accrue_all_regeneration(duration_ms)
    for state in states.values():
        state.expire_reductions(duration_ms)
        state.expire_statuses(duration_ms)
        state.update_shields(duration_ms)
        state.expire_stat_modifiers(duration_ms)
        state.expire_death_preventions(duration_ms)
        state.expire_max_health(duration_ms)

    return TimelineResult(
        duration_ms=duration_ms,
        horizon_ms=horizon_ms,
        actor_at_horizon=horizon_snapshots[EntityId.ACTOR],
        target_at_horizon=horizon_snapshots[EntityId.TARGET],
        actor_at_end=states[EntityId.ACTOR].snapshot(),
        target_at_end=states[EntityId.TARGET].snapshot(),
        damage_to_target_first_horizon=horizon_damage_by_target[EntityId.TARGET],
        damage_to_target_total=damage_by_target[EntityId.TARGET],
        target_dead_at_horizon=horizon_snapshots[EntityId.TARGET].dead,
        log=tuple(log),
        targets_at_horizon={
            entity: snapshot
            for entity, snapshot in horizon_snapshots.items()
            if entity not in ALLY_ENTITIES
        },
        targets_at_end={
            entity: state.snapshot()
            for entity, state in states.items()
            if entity not in ALLY_ENTITIES
        },
        damage_by_target_first_horizon=dict(horizon_damage_by_target),
        damage_by_target_total=dict(damage_by_target),
        allies_at_horizon={
            entity: snapshot
            for entity, snapshot in horizon_snapshots.items()
            if entity in ALLY_ENTITIES
        },
        allies_at_end={
            entity: state.snapshot() for entity, state in states.items() if entity in ALLY_ENTITIES
        },
        damage_by_source_first_horizon=dict(horizon_damage_by_source),
        damage_by_source_total=dict(damage_by_source),
        death_ms_by_entity=dict(death_ms_by_entity),
        healing_by_entity=dict(healing_by_entity),
        healing_prevented_by_entity=dict(healing_prevented_by_entity),
        healing_prevented_by_source=dict(healing_prevented_by_source),
    )
