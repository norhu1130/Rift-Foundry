"""Champion Cog modules with a documented champion-scoped mechanism gap.

Maturity is still ``CogMaturity.MODELED_UNVERIFIED`` — the core rotation is
implemented from locked data and passes its regression tests — but at least
one ability's reaction or action plan carries a literal blocker beyond the
standard ``COG_MODEL_UNVERIFIED:<champion>`` one (for example
``KATARINA_R_CHANNEL_INTERRUPTION_AND_PER_TARGET_TICKS_NOT_MODELED``),
meaning some mechanism was explicitly excluded or approximated rather than
computed from locked data. See :mod:`..modeled_unverified` for Cogs with no
such gap.

A module lives here only while ``tests/test_all_champion_modules.py``'s
``_has_champion_scoped_mechanism_gap`` scan finds such a blocker in its
source; adding or removing one without moving the file fails that test.
"""
