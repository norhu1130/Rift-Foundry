"""Role-neutral contracts for champion-specific mechanics.

Like a discord.py Cog, a champion Cog owns related behavior while the registry
and dispatcher own lifecycle and routing.  A Cog is never an "attacker Cog" or
"target Cog"; the entity role is supplied in :class:`ParticipantContext` for
each matchup request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any

from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    DamageOutput,
    EntityId,
    opponent_sequence_offset,
)


class CogMaturity(StrEnum):
    """Classify how far a champion Cog has progressed through verification."""

    SCAFFOLDED = "SCAFFOLDED"
    MODELED_UNVERIFIED = "MODELED_UNVERIFIED"
    VERIFIED = "VERIFIED"


class CogCapability(StrEnum):
    """Name independently testable behavior exposed by a champion Cog."""

    BASIC_ATTACK = "BASIC_ATTACK"
    ABILITY_ROTATION = "ABILITY_ROTATION"
    REACTION_MODEL = "REACTION_MODEL"
    ENGAGEMENT = "ENGAGEMENT"
    ITEM_POLICY = "ITEM_POLICY"
    MULTI_TARGET = "MULTI_TARGET"
    RECOMMENDATION = "RECOMMENDATION"


#: Locked targeting types whose effect unambiguously covers an area rather than
#: one champion. ``Location``, ``LocationClamped``, ``Direction`` and the
#: terrain variants are deliberately excluded: a point or line cast may still
#: resolve on a single champion, and the locked data does not say which.
AREA_TARGETING_TYPES: frozenset[str] = frozenset({"SelfAoe", "Area", "AreaClamped", "Cone"})

#: Ability slots in the order the locked character record lists them.
ABILITY_SLOTS: tuple[str, ...] = ("Q", "W", "E", "R")

#: Attack range at or below which a champion has to stand in the front line to
#: fight. League records no melee flag, so this threshold is a modeling choice.
MELEE_RANGE_CEILING = Decimal(325)


#: Capabilities a Cog can claim by modeling a one-versus-one encounter alone.
#: Declaring the whole :class:`CogCapability` enum would hand every Cog each
#: capability invented later, so behavior that needs its own evidence — such as
#: :attr:`CogCapability.MULTI_TARGET` — is deliberately excluded and must be
#: declared by the Cogs that actually implement it.
DUEL_CAPABILITIES: frozenset[CogCapability] = frozenset(CogCapability) - {
    CogCapability.MULTI_TARGET
}


class ControlType(StrEnum):
    """Identify crowd-control semantics independently from action channels."""

    ALL = "ALL"
    AIRBORNE = "AIRBORNE"
    BLIND = "BLIND"
    CHARM = "CHARM"
    DISARM = "DISARM"
    DROWSY = "DROWSY"
    FEAR = "FEAR"
    ROOT = "ROOT"
    SILENCE = "SILENCE"
    SLEEP = "SLEEP"
    SLOW = "SLOW"
    STUN = "STUN"
    SUPPRESSION = "SUPPRESSION"
    TAUNT = "TAUNT"
    UNSPECIFIED = "UNSPECIFIED"


@dataclass(frozen=True)
class CogMetadata:
    """Expose machine-readable implementation and evidence metadata."""

    maturity: CogMaturity
    capabilities: frozenset[CogCapability]
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChampionSnapshot:
    """Hold combat-ready champion stats after item aggregation."""

    champion_id: int
    champion_key: str
    level: int
    max_hp: Decimal
    attack_damage: Decimal
    armor: Decimal
    magic_resistance: Decimal
    attack_speed: Decimal
    move_speed: Decimal
    attack_range: Decimal
    bonus_health: Decimal = Decimal(0)
    critical_strike_chance: Decimal = Decimal(0)
    ability_power: Decimal = Decimal(0)
    bonus_attack_damage: Decimal = Decimal(0)
    percent_armor_penetration: Decimal = Decimal(0)
    flat_armor_penetration: Decimal = Decimal(0)
    percent_magic_penetration: Decimal = Decimal(0)
    flat_magic_penetration: Decimal = Decimal(0)
    tenacity: Decimal = Decimal(0)
    ability_haste: Decimal = Decimal(0)
    life_steal: Decimal = Decimal(0)
    omnivamp: Decimal = Decimal(0)
    health_regen_per_second: Decimal = Decimal(0)
    critical_strike_damage: Decimal = Decimal(2)
    heal_shield_power: Decimal = Decimal(0)


@dataclass(frozen=True)
class OpponentView:
    """Bind one opposing participant to its timeline entity."""

    entity: EntityId
    snapshot: ChampionSnapshot


@dataclass(frozen=True)
class ParticipantContext:
    """Bind a role-neutral Cog to one side of a concrete encounter.

    ``opponent_entity`` and ``opponent_snapshot`` name the participant this Cog
    is currently aimed at, which is the whole opposing side in a duel. A Cog
    whose abilities reach further than that reads :attr:`opposing_side` instead,
    which lists every opponent present in the encounter.
    """

    self_entity: EntityId
    opponent_entity: EntityId
    snapshot: ChampionSnapshot
    opponent_snapshot: ChampionSnapshot
    duration_ms: int
    horizon_ms: int
    opponents: tuple[OpponentView, ...] = ()

    @property
    def opposing_side(self) -> tuple[OpponentView, ...]:
        """List every opponent, falling back to the aimed-at participant alone.

        :return: Opposing participants in canonical entity order.
        """
        if self.opponents:
            return self.opponents
        return (OpponentView(self.opponent_entity, self.opponent_snapshot),)

    @property
    def faces_multiple_opponents(self) -> bool:
        """Report whether more than one opponent is present.

        :return: ``True`` when the encounter is not a duel.
        """
        return len(self.opposing_side) > 1


@dataclass(frozen=True)
class ActionPlan:
    """Describe a champion's deterministic outgoing action schedule."""

    model_id: str
    events: tuple[ActionEvent, ...]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CastBlockWindow:
    """Describe an action-control interval caused by a source event."""

    id: str
    start_ms: int
    end_ms: int
    blocked_channels: tuple[ActionChannel, ...]
    source_event_id: str | None = None
    tenacity_reducible: bool = False
    control_type: ControlType = ControlType.UNSPECIFIED


@dataclass(frozen=True)
class ControlImmunityWindow:
    """Suppress incoming control without suppressing its source event damage."""

    id: str
    start_ms: int
    end_ms: int
    recipient: EntityId
    control_types: tuple[ControlType, ...]
    source_event_id: str | None = None

    def blocks(self, control_type: ControlType) -> bool:
        """Report whether this window rejects one incoming control type.

        :param control_type: Normalized type attached to an incoming control effect.
        :return: ``True`` for an exact match or universal immunity.
        """
        return ControlType.ALL in self.control_types or control_type in self.control_types


@dataclass(frozen=True)
class AttackCadenceModifierWindow:
    """Alter basic-attack clock progress during a causally linked interval."""

    id: str
    start_ms: int
    end_ms: int
    multiplier: Decimal
    source_event_id: str | None = None


@dataclass(frozen=True)
class ReactionPlan:
    """Describe defensive events, damage windows, and control reactions."""

    model_id: str
    events: tuple[ActionEvent, ...] = ()
    damage_windows: tuple[DamageModifierWindow, ...] = ()
    cast_block_windows: tuple[CastBlockWindow, ...] = ()
    control_immunity_windows: tuple[ControlImmunityWindow, ...] = ()
    attack_cadence_windows: tuple[AttackCadenceModifierWindow, ...] = ()
    blockers: tuple[str, ...] = ()


class ChampionCog:
    """Base Cog usable in either participant position."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    evidence_refs: tuple[str, ...] = ()

    def __init__(
        self,
        champion_document: dict[str, Any],
        detail_root: dict[str, Any] | None = None,
        detail_document: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a Cog from locked champion documents.

        :param champion_document: Data Dragon champion summary document.
        :param detail_root: Optional CommunityDragon stat detail document.
        :param detail_document: Optional full CommunityDragon record set, which
            holds the spell records the character record only points at.
        :return: None.
        """
        self.document = champion_document
        self.detail_root = detail_root
        self.detail_document = detail_document
        self.champion_id = int(champion_document["key"])
        self.champion_key = str(champion_document["id"])
        self.name = str(champion_document["name"])
        self.aliases = frozenset(
            {
                self.champion_key.casefold(),
                self.name.casefold(),
                str(self.champion_id),
            }
        )

    @property
    def metadata(self) -> CogMetadata:
        """Return explicit model maturity, capabilities, and evidence references.

        :return: Immutable metadata declared by the concrete Cog class.
        """
        return CogMetadata(self.maturity, self.capabilities, self.evidence_refs)

    def area_ability_slots(self) -> frozenset[str]:
        """Report which ability slots the locked data marks as area effects.

        The character record lists spells in ``Q, W, E, R`` order and each spell
        declares a targeting type. Only types that cannot resolve on a single
        champion are reported, so a Cog never widens an ability on a guess.

        :return: Slot letters whose locked targeting type covers an area.
        """
        root = self.detail_root or {}
        spells = root.get("spells")
        if not isinstance(spells, list):
            return frozenset()
        found: set[str] = set()
        for slot, spell_path in zip(ABILITY_SLOTS, spells, strict=False):
            if self._targeting_type(spell_path) in AREA_TARGETING_TYPES:
                found.add(slot)
        return frozenset(found)

    def _targeting_type(self, spell_path: str) -> str | None:
        """Resolve one spell path to its locked targeting type.

        :param spell_path: Spell record path taken from the character record.
        :return: Targeting type name, or ``None`` when the record is absent.
        """
        document = self.detail_document or {}
        tail = spell_path.split("/")[-1]
        record = next(
            (
                value
                for key, value in document.items()
                if key.endswith(f"/{tail}") and isinstance(value, dict)
            ),
            None,
        )
        spell = record.get("mSpell") if isinstance(record, dict) else None
        data = spell.get("mTargetingTypeData") if isinstance(spell, dict) else None
        return data.get("__type") if isinstance(data, dict) else None

    @staticmethod
    def area_recipients(
        context: ParticipantContext,
        *,
        centered_on_self: bool,
    ) -> tuple[EntityId, ...]:
        """List the opponents an area ability plausibly covers.

        The encounter carries no positions, so reach is approximated from the
        one positional fact the patch data records: attack range, which decides
        whether a champion has to stand in the front line to fight.

        A caster-centered effect covers whoever is standing on the caster —
        opponents that must close to attack it, plus the opponent the caster
        itself closed on. A point or cone effect is placed on the caster's
        target, so it covers that target and the opponents sharing its line.

        A duel holds one opponent, which is also the aimed-at one, so both
        readings return exactly that opponent and duel output is unchanged.

        :param context: Role-bound participant context for one Cog invocation.
        :param centered_on_self: Whether the effect originates on the caster.
        :return: Covered opponent identifiers in canonical order.
        """
        side = context.opposing_side
        focus = context.opponent_entity
        if centered_on_self:
            return tuple(
                view.entity
                for view in side
                if view.entity == focus or view.snapshot.attack_range <= MELEE_RANGE_CEILING
            )
        focus_is_melee = next(
            (
                view.snapshot.attack_range <= MELEE_RANGE_CEILING
                for view in side
                if view.entity == focus
            ),
            True,
        )
        return tuple(
            view.entity
            for view in side
            if view.entity == focus
            or (view.snapshot.attack_range <= MELEE_RANGE_CEILING) == focus_is_melee
        )

    @classmethod
    def area_outputs(
        cls,
        context: ParticipantContext,
        build: Callable[[EntityId], Any],
        *,
        centered_on_self: bool = False,
    ) -> tuple[Any, ...]:
        """Repeat one output for every opponent an area ability reaches.

        :param context: Role-bound participant context for one Cog invocation.
        :param build: Factory producing one output for a given recipient.
        :param centered_on_self: Whether the effect originates on the caster.
        :return: One output per covered opponent, in canonical order.
        """
        return tuple(
            build(entity)
            for entity in cls.area_recipients(context, centered_on_self=centered_on_self)
        )

    def has_capability(self, capability: CogCapability) -> bool:
        """Report whether this Cog explicitly implements one behavior.

        :param capability: Behavior required by the caller.
        :return: ``True`` only when the concrete Cog declares the capability.
        """
        return capability in self.capabilities

    def verification_blockers(self) -> tuple[str, ...]:
        """Return release blockers implied by this Cog's maturity.

        :return: Empty output for verified Cogs or one champion-scoped blocker.
        """
        if self.maturity is CogMaturity.VERIFIED:
            return ()
        if self.maturity is CogMaturity.MODELED_UNVERIFIED:
            return (f"COG_MODEL_UNVERIFIED:{self.champion_key}",)
        return (f"COG_SCAFFOLDED:{self.champion_key}",)

    @property
    def qualified_name(self) -> str:
        """Return the stable registry key for this Cog.

        :return: ``champion:<Data Dragon id>``.
        """
        return f"champion:{self.champion_key}"

    @staticmethod
    def growth_multiplier(level: int) -> Decimal:
        """Calculate Riot's nonlinear champion-stat growth multiplier.

        :param level: Champion level in the inclusive range 1 through 18.
        :return: Growth multiplier applied to per-level stats.
        :raises ValueError: If ``level`` is outside the supported range.
        """
        if not 1 <= level <= 18:
            raise ValueError("champion level must be within [1, 18]")
        levels = Decimal(level - 1)
        return levels * (Decimal("0.7025") + Decimal("0.0175") * levels)

    def snapshot(
        self,
        *,
        level: int,
        item_stats: dict[str, Decimal] | None = None,
    ) -> ChampionSnapshot:
        """Build an immutable champion snapshot for one item state.

        :param level: Champion level used for stat growth.
        :param item_stats: Normalized aggregate item modifiers.
        :return: Combat-ready champion snapshot.
        """
        stats = self.document["stats"]
        items = item_stats or {}
        growth = self.growth_multiplier(level)
        detail = self.detail_root or {}

        def value(key: str, fallback: str) -> Decimal:
            """Resolve one detailed stat with a summary fallback.

            :param key: CommunityDragon stat key.
            :param fallback: Data Dragon summary key.
            :return: Resolved decimal stat value.
            """
            raw = detail.get(key)
            if isinstance(raw, dict) and "baseValue" in raw:
                return Decimal(str(raw["baseValue"]))
            return Decimal(str(stats[fallback]))

        max_hp = (
            value("baseHPModifiable", "hp")
            + value("hpPerLevelModifiable", "hpperlevel") * growth
            + items.get("HP", Decimal(0))
        )
        attack_damage = (
            value("baseDamageModifiable", "attackdamage")
            + value("damagePerLevelModifiable", "attackdamageperlevel") * growth
            + items.get("AD", Decimal(0))
        )
        attack_speed = (
            value("attackSpeedModifiable", "attackspeed")
            + value("attackSpeedRatioModifiable", "attackspeed")
            * (
                value("attackSpeedPerLevelModifiable", "attackspeedperlevel")
                * growth
                / Decimal(100)
                + items.get("ATTACK_SPEED", Decimal(0))
            )
        ) * items.get("ATTACK_SPEED_MULTIPLIER", Decimal(1))
        return ChampionSnapshot(
            self.champion_id,
            self.champion_key,
            level,
            max_hp,
            attack_damage,
            value("baseArmorModifiable", "armor")
            + value("armorPerLevelModifiable", "armorperlevel") * growth
            + items.get("ARMOR", Decimal(0)),
            value("baseMR", "spellblock")
            + value("mrPerLevel", "spellblockperlevel") * growth
            + items.get("MAGIC_RESISTANCE", Decimal(0)),
            attack_speed,
            (
                value("baseMoveSpeedModifiable", "movespeed")
                + items.get("MOVE_SPEED_FLAT", Decimal(0))
            )
            * (Decimal(1) + items.get("MOVE_SPEED_PERCENT", Decimal(0))),
            value("attackRangeModifiable", "attackrange"),
            items.get("HP", Decimal(0)),
            items.get("CRITICAL_STRIKE_CHANCE", Decimal(0)),
            items.get("AP", Decimal(0)),
            items.get("AD", Decimal(0)),
            items.get("PERCENT_ARMOR_PENETRATION", Decimal(0)),
            # Lethality converts 1:1 to flat armor penetration at every level
            # since V14.1; the older 60% + 40% x level / 18 scaling is gone.
            items.get("FLAT_ARMOR_PENETRATION", Decimal(0)),
            items.get("PERCENT_MAGIC_PENETRATION", Decimal(0)),
            items.get("FLAT_MAGIC_PENETRATION", Decimal(0)),
            items.get("TENACITY", Decimal(0)),
            items.get("ABILITY_HASTE", Decimal(0)),
            items.get("LIFESTEAL", Decimal(0)),
            items.get("OMNIVAMP", Decimal(0)),
            # Data Dragon records base regeneration per five seconds; items with
            # a base-regeneration modifier scale only that base value.
            (
                Decimal(str(stats.get("hpregen", 0)))
                + Decimal(str(stats.get("hpregenperlevel", 0))) * growth
            )
            / Decimal(5)
            * (Decimal(1) + items.get("BASE_HEALTH_REGEN_PERCENT", Decimal(0))),
            # A critical strike deals the champion's locked ``critDamageMultiplier``
            # (2.0 for every champion except Ashe's 1.0) plus item bonuses such
            # as Infinity Edge's ``mFlatCritDamageMod``.
            critical_strike_damage=Decimal(str(detail.get("critDamageMultiplier", 2)))
            + items.get("CRITICAL_STRIKE_DAMAGE", Decimal(0)),
            heal_shield_power=items.get("HEAL_SHIELD_POWER", Decimal(0)),
        )

    @staticmethod
    def _sequence_base(context: ParticipantContext) -> int:
        """Reserve a disjoint deterministic sequence range for each participant.

        :param context: Role-bound participant context for one Cog invocation.
        :return: Disjoint block start for this participant's action events.
        """
        entity = context.self_entity
        base = 0 if entity is EntityId.ACTOR else 10_000
        return base + opponent_sequence_offset(entity)

    @staticmethod
    def _level_breakpoint_value(
        level1_value: Decimal,
        initial_bonus_per_level: Decimal,
        breakpoints: tuple[tuple[int, Decimal], ...],
        level: int,
    ) -> Decimal:
        """Evaluate a locked ``ByCharLevelBreakpoints`` formula at one level.

        The per-level increment starts as ``initial_bonus_per_level`` and
        switches to a breakpoint's own increment starting at that breakpoint's
        level, inclusive — matching the locked field name
        ``mBonusPerLevelAtAndAfter``, which reads "at and after this level."
        Callers that use this method attach an
        ``..._LEVEL_CURVE_CONVENTION_ASSUMED`` blocker, since the raw record
        does not state the convention in prose and this is the literal but
        unverified reading of the field name.

        :param level1_value: Locked value at champion level one.
        :param initial_bonus_per_level: Per-level increment before the first
            breakpoint.
        :param breakpoints: Ascending ``(level, bonus_per_level)`` pairs.
        :param level: Champion level to evaluate, at least one.
        :return: Formula value at the given level.
        :raises ValueError: If level is below one.
        """
        if level < 1:
            raise ValueError("level must be at least one")
        value = level1_value
        bonus = initial_bonus_per_level
        pending = list(breakpoints)
        for current in range(2, level + 1):
            while pending and current >= pending[0][0]:
                bonus = pending[0][1]
                pending.pop(0)
            value += bonus
        return value

    @staticmethod
    def _attack_interval_ms(attack_speed: Decimal) -> int:
        """Convert attacks per second to the shared rounded attack interval.

        :param attack_speed: Positive attacks-per-second value after modifiers.
        :return: Deterministic interval in milliseconds, with a one-ms floor.
        :raises ValueError: If attack speed is zero or negative.
        """
        if attack_speed <= 0:
            raise ValueError("attack_speed must be positive")
        return max(
            1,
            int((Decimal(1000) / attack_speed).to_integral_value(ROUND_HALF_EVEN)),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Return a deterministic basic-attack fallback for an uncurated rotation.

        :param context: Participant and opponent snapshots for this encounter.
        :return: Basic-attack schedule with an explicit curation blocker.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        events: list[ActionEvent] = []
        at_ms = 200
        sequence = self._sequence_base(context)
        while at_ms <= context.duration_ms:
            events.append(
                ActionEvent(
                    f"{context.snapshot.champion_key.upper()}_GENERIC_ATTACK_{sequence}",
                    at_ms,
                    sequence,
                    context.self_entity,
                    ActionChannel.BASIC_ATTACK,
                    (
                        DamageOutput(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            sequence += 1
            at_ms += interval_ms
        return ActionPlan(
            "generic_basic_attack_v1",
            tuple(events),
            (f"ROTATION_UNCURATED:{self.champion_key}", *self.verification_blockers()),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return the neutral fallback reaction model.

        :param context: Participant and opponent snapshots for this encounter.
        :return: Empty reaction plan carrying an uncurated-model blocker.
        """
        return ReactionPlan(
            "neutral_reaction_v1",
            blockers=(
                f"REACTIONS_UNCURATED:{self.champion_key}",
                *self.verification_blockers(),
            ),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return a curated champion-kit pursuit multiplier for the benchmark.

        :param context: Concrete participant context.
        :return: Multiplicative movement-speed factor.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return displacement available for closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(0)

    def engagement_target_slow_fraction(self, context: ParticipantContext) -> Decimal:
        """Return the slow this kit applies to a retreating opponent.

        Combined multiplicatively with item slows in the pursuit benchmark, so a
        kit slow closes distance without being disguised as self movement speed.

        :param context: Concrete participant context.
        :return: Slow fraction in ``[0, 1)``.
        """
        return Decimal(0)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Estimate champion-native recovery outside the duel timeline.

        :param context: Concrete participant context.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before recovery begins.
        :return: Recovered health and evidence blockers.
        """
        return Decimal(0), ()

    def item_candidate_blocker(self, item: dict[str, Any]) -> str | None:
        """Reject items whose value the curated Cog cannot represent.

        :param item: Normalized locked item document.
        :return: Blocker code, or ``None`` when model-compatible.
        """
        return None
