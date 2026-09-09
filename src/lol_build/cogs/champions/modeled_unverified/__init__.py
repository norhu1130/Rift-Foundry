"""Champion Cog modules with no documented champion-scoped mechanism gap.

Maturity is ``CogMaturity.MODELED_UNVERIFIED``: the rotation is fully
implemented from locked patch data and passes its regression tests, and no
ability's reaction or action plan carries a blocker beyond the standard
``COG_MODEL_UNVERIFIED:<champion>`` one. What remains is verification against
a live client (see TASKS.md P0-041), not further implementation work. See
:mod:`..wip` for Cogs that still exclude or approximate a specific mechanism.

A module lives here only while ``tests/test_all_champion_modules.py``'s
``_has_champion_scoped_mechanism_gap`` scan finds no such blocker in its
source; adding one without moving the file fails that test.
"""
