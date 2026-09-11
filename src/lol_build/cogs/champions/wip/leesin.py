"""Lee Sin combat Cog backed by locked 16.17.1 source documents."""

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, StatModifierOutput


class LeeSinCog(ChampionCog):
    """Model Lee Sin's level-13 Q5/E5/R2/W1 confirmed-hit combo.

    Safeguard is self-cast first for its rank-one ``ShieldAmount``, and Iron
    Will then grants its rank-one ``LifestealAndSpellVamp`` (10%) for
    ``LifestealAndSpellVampTime`` (4 s), covering the Q-Q-R combo.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/LeeSin.json",
        "data/raw/16.17.1/communitydragon/champions/64.json",
        "data/raw/16.17.1/communitydragon/champions/leesin.bin.json",
    )

    def engagement_speed_multiplier(self, c: ParticipantContext) -> Decimal:
        """Return neutral speed because Sonic Wave supplies the modeled entry.

        :param c: Role-bound Lee Sin encounter context.
        :return: Neutral multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, c: ParticipantContext) -> Decimal:
        """Return Resonating Strike's displayed dash distance.

        :param c: Role-bound Lee Sin encounter context.
        :return: Dash reach in game units.
        """
        return Decimal(1300)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unmodeled resource, sustain, and critical channels.

        :param item: Normalized locked item candidate.
        :return: Lee Sin-specific blocker or ``None``.
        """
        s = item["stats"]
        assert isinstance(s, dict)
        u = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & s.keys()
        return f"LEESIN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(u))}" if u else None

    def build_action_plan(self, c: ParticipantContext) -> ActionPlan:
        """Build confirmed Q, E, and R hits with basic attacks.

        :param c: Role-bound snapshots and duration.
        :return: Deterministic combo with missing-health blockers.
        """
        b = self._sequence_base(c)
        ad = c.snapshot.bonus_attack_damage
        ev = [
            action(
                "LEESIN_W_SAFEGUARD_SELF",
                at_ms=0,
                sequence=b + 3,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        c.self_entity,
                        Decimal(60) + Decimal("0.8") * c.snapshot.ability_power,
                        duration_ms=2000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "LEESIN_W_IRON_WILL",
                at_ms=50,
                sequence=b + 4,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(c.self_entity, "LIFESTEAL", Decimal("0.10"), 4000),
                    StatModifierOutput(c.self_entity, "ABILITY_VAMP", Decimal("0.10"), 4000),
                ),
                requires_living_opponent=False,
            ),
            action(
                "LEESIN_Q_SONIC_WAVE",
                at_ms=100,
                sequence=b,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(180) + Decimal("1.0") * ad, DamageType.PHYSICAL
                    ),
                ),
            ),
            action(
                "LEESIN_Q_RESONATING_STRIKE",
                at_ms=400,
                sequence=b + 1,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(180) + Decimal("1.0") * ad, DamageType.PHYSICAL
                    ),
                ),
            ),
            action(
                "LEESIN_R_DRAGONS_RAGE",
                at_ms=800,
                sequence=b + 2,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(600) + Decimal("2.0") * ad, DamageType.PHYSICAL
                    ),
                ),
            ),
        ]
        return ActionPlan(
            "leesin_q5_e5_r2_level13_combo_v1",
            tuple(sorted(ev, key=lambda event: (event.at_ms, event.sequence))),
            (
                "LEESIN_LEVEL13_RANK_POLICY_UNVERIFIED",
                "LEESIN_Q_HIT_AND_RECAST_TIMING_UNVERIFIED",
                "LEESIN_Q_MISSING_HEALTH_DAMAGE_NOT_MODELED",
                "LEESIN_R_DISPLACEMENT_NOT_MODELED",
                "LEESIN_W_SELF_CAST_BEFORE_COMBO_ASSUMED",
            ),
        )

    def build_reaction_plan(self, c: ParticipantContext) -> ReactionPlan:
        """Keep Safeguard and Iron Will absent without ally and sustain state.

        :param c: Role-bound Lee Sin encounter context.
        :return: Explicit defensive-state blockers.
        """
        return ReactionPlan(
            "leesin_safeguard_reaction_v1",
            blockers=("LEESIN_W_ALLY_TARGET_REQUIRES_ALLIES",),
        )
