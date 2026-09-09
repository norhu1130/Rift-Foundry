"""Dedicated champion Cog modules for the locked champion roster.

Each champion owns one physical module. Shared combat behavior remains in the
base Cog and mechanics layers, while these modules provide stable extension
points for champion-specific rotations, reactions, and item policies.

Modules are grouped by :class:`~lol_build.cogs.base.CogMaturity` (and, within
``MODELED_UNVERIFIED``, by whether a champion-scoped mechanism gap is
documented) into folders mirrored by the web UI's own status labels:

- ``todo/`` — ``SCAFFOLDED``. No behavior beyond the generic basic-attack
  fallback; the champion has not been curated yet.
- ``modeled_unverified/`` — ``MODELED_UNVERIFIED`` with no documented
  mechanism gap. A rotation is fully implemented from locked patch data and
  passes its regression tests; only client verification remains.
- ``wip/`` — ``MODELED_UNVERIFIED`` with a documented mechanism gap: at least
  one ability's blockers cite a specific excluded or approximated mechanic
  (e.g. a resource-stack system, a state-dependent trigger), so the
  implementation itself is still incomplete, not just unverified.
- ``curated/`` — ``VERIFIED``. Modeled and verified. Empty today: no Cog has
  reached this state (see TASKS.md P0-041, which blocks verification on a
  16.17.1 client measurement session).

A module's folder must always match its manifest maturity (and, for
``MODELED_UNVERIFIED``, its mechanism-gap status); moving a file without
updating ``manifest.py`` — or leaving it in place after its blockers change —
is caught by ``tests/test_all_champion_modules.py``.
"""
