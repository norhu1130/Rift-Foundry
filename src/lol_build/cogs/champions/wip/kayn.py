"""Kayn combat Cog backed by locked 16.17.1 source documents."""

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel


class KaynCog(ChampionCog):
    """Model Kayn's level-13 Q5/W5/R2 baseline rotation.

    Form choice, wall traversal, and Umbral Trespass attachment state are not
    derivable from the two-participant benchmark and remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kayn.json",
        "data/raw/16.17.1/communitydragon/champions/141.json",
        "data/raw/16.17.1/communitydragon/champions/kayn.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return the neutral multiplier because Shadow Step terrain is unknown.

        :param context: Role-bound Kayn encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return Reaping Slash's locked dash reach.

        :param context: Role-bound Kayn encounter context.
        :return: Modeled dash distance in game units.
        """
        return Decimal(350)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject channels not consumed by Kayn's deterministic damage model.

        :param item: Normalized item candidate from the locked catalog.
        :return: A Kayn-specific blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        return (
            f"KAYN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build a deterministic Q, W, R and sustained-attack rotation.

        :param context: Role-bound combat snapshots and duration.
        :return: Locked-value action events with honest state blockers.
        """
        base = self._sequence_base(context)
        ad, bonus = context.snapshot.attack_damage, context.snapshot.bonus_attack_damage
        events = [
            action(
                "KAYN_Q_REAPING_SLASH",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(195) + Decimal("1.3") * bonus,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KAYN_W_BLADES_REACH",
                at_ms=500,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(265) + Decimal("1.0") * bonus,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(context.opponent_entity, "SLOW", duration_ms=1500),
                ),
            ),
            action(
                "KAYN_R_UMBRAL_TRESPASS",
                at_ms=1400,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("1.75") * bonus,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        for index, at_ms in enumerate(range(900, context.duration_ms + 1, interval), 1):
            events.append(
                action(
                    f"KAYN_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, ad, DamageType.PHYSICAL),),
                )
            )
        return ActionPlan(
            "kayn_q5_w5_r2_level13_rotation_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                "KAYN_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KAYN_FORM_SELECTION_NOT_MODELED",
                "KAYN_R_ATTACHMENT_AND_MISSING_HEALTH_NOT_MODELED",
                "KAYN_W_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the causal Blade's Reach slow as a movement restriction.

        :param context: Role-bound Kayn encounter context.
        :return: Reaction control window and unmodeled-form blockers.
        """
        return ReactionPlan(
            "kayn_w_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "kayn_w_slow",
                    500,
                    min(2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "KAYN_W_BLADES_REACH",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=("KAYN_W_SLOW_MAGNITUDE_UNVERIFIED", "KAYN_FORM_REACTIONS_NOT_MODELED"),
        )
