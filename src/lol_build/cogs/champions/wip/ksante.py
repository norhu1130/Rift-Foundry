"""K'Sante combat Cog backed by locked 16.17.1 source documents."""

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel


class KSanteCog(ChampionCog):
    """Model K'Sante's level-13 Q5/W5/E1 baseline without All Out state."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/KSante.json",
        "data/raw/16.17.1/communitydragon/champions/897.json",
        "data/raw/16.17.1/communitydragon/champions/ksante.bin.json",
    )

    def engagement_speed_multiplier(self, c: ParticipantContext) -> Decimal:
        """Return neutral speed outside All Out.

        :param c: Role-bound K'Sante encounter context.
        :return: Neutral multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, c: ParticipantContext) -> Decimal:
        """Return Footwork's self-target dash reach.

        :param c: Role-bound K'Sante encounter context.
        :return: Dash reach in game units.
        """
        return Decimal(250)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels not resolved by this baseline.

        :param item: Normalized locked item candidate.
        :return: K'Sante-specific blocker or ``None``.
        """
        s = item["stats"]
        assert isinstance(s, dict)
        u = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & s.keys()
        return f"KSANTE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(u))}" if u else None

    def build_action_plan(self, c: ParticipantContext) -> ActionPlan:
        """Build Q strikes and basic attacks in the non-All-Out form.

        :param c: Role-bound snapshots and duration.
        :return: Deterministic plan with transformation blockers.
        """
        b = self._sequence_base(c)
        ev = [
            action(
                "KSANTE_Q_NTOFO_STRIKES",
                at_ms=100,
                sequence=b,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity,
                        Decimal(120) + Decimal("0.40") * c.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KSANTE_W_PATH_MAKER",
                at_ms=500,
                sequence=b + 1,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity,
                        Decimal(100) + Decimal("0.50") * c.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        for i, t in enumerate(
            range(800, c.duration_ms + 1, self._attack_interval_ms(c.snapshot.attack_speed)), 1
        ):
            ev.append(
                action(
                    f"KSANTE_BASIC_ATTACK_{i}",
                    at_ms=t,
                    sequence=b + 100 + i,
                    source=c.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(c.opponent_entity, c.snapshot.attack_damage, DamageType.PHYSICAL),
                    ),
                )
            )
        return ActionPlan(
            "ksante_q5_w5_e1_level13_rotation_v1",
            tuple(sorted(ev, key=lambda e: (e.at_ms, e.sequence))),
            (
                "KSANTE_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KSANTE_PASSIVE_STACKS_NOT_MODELED",
                "KSANTE_R_ALL_OUT_NOT_MODELED",
                "KSANTE_W_CHARGE_STATE_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, c: ParticipantContext) -> ReactionPlan:
        """Keep Path Maker reduction absent until charge timing is verified.

        :param c: Role-bound K'Sante encounter context.
        :return: Reaction blocker plan.
        """
        return ReactionPlan(
            "ksante_path_maker_reaction_v1", blockers=("KSANTE_W_DAMAGE_REDUCTION_NOT_MODELED",)
        )
