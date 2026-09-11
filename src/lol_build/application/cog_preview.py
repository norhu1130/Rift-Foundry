"""Bounded generic build search for Cogs with a curated action model."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from lol_build.application.item_combat import duplicate_group_blockers, item_engagement_modifiers
from lol_build.application.progress import ProgressCallback, report_progress
from lol_build.cogs import ParticipantContext
from lol_build.core.timeline import DamageOutput, EntityId
from lol_build.items.progression import (
    simulate_engagement,
    simulate_heartsteel_progression,
    simulate_lane_sustain,
    warmog_heart_ready,
)
from lol_build.recommendation.context import (
    OutcomeStatus,
    RecommendationAssumptions,
    RecommendationState,
    ScopeStatus,
    VerificationStatus,
    pregame_assumptions,
)
from lol_build.recommendation.explanation import (
    BuildExplanation,
    build_explanation,
    build_slot_runner_up,
)
from lol_build.recommendation.feasibility import defense_candidate_is_feasible
from lol_build.recommendation.readiness import RecommendationScope, RecommendationStatus
from lol_build.recommendation.selection import BranchId

#: Pursuit benchmark length the engagement metrics are measured over.
_PURSUIT_WINDOW_MS = 3000

#: How the pursuit benchmark assumes the target behaves. Whether an opponent
#: runs is a player decision the patch data does not record, so the readings are
#: named rather than assumed silently.
PURSUIT_TARGET_POLICIES = ("range_aware", "always_flees", "stands_ground")

#: Default target behavior. A target that always flees at its own move speed is
#: uncatchable whenever the actor has no movement advantage, which turns the
#: engagement metric into a test for movement items rather than for engagement.
#: Reach decides instead: an opponent that outranges the actor gains from
#: kiting, while one that must close to deal damage has no reason to run.
_DEFAULT_PURSUIT_TARGET_POLICY = "range_aware"

#: Default crediting for short, cooldown-bound item actives: the share of
#: wall-clock time the active is actually up (``duration / cooldown``), not
#: how much of the pursuit window its duration alone covers. The latter
#: ("per_engagement") assumes every active is saved for exactly this fight
#: regardless of its cooldown, which let a ninety-second-cooldown item's
#: incidental movement grant compete as if it were always available and
#: measurably win item slots on that side effect alone (P1-070; see
#: ``TASKS.md``).
_DEFAULT_ACTIVE_DUTY_POLICY = "uncorrelated"


@dataclass(frozen=True)
class CogPreviewBranch:
    """Represent one selected build branch and its independent metrics."""

    branch: BranchId
    item_ids: tuple[int, ...]
    metrics: dict[str, Decimal]
    explanation: BuildExplanation


@dataclass(frozen=True)
class CogBuildPreview:
    """Represent a non-release generic three-core Cog recommendation."""

    recommendation_status: RecommendationStatus
    state: RecommendationState
    assumptions: RecommendationAssumptions
    scope: RecommendationScope
    preview_kind: str
    release_eligible: bool
    actor_cog: str
    opponent_cog: str
    branches: dict[BranchId, CogPreviewBranch]
    evaluated_candidate_count: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class _BeamState:
    """Accumulate weighted metrics and readiness across ordered core stages."""

    item_ids: tuple[int, ...]
    damage_weighted: Decimal
    survival_weighted: Decimal
    survival_ms_weighted: Decimal
    engagement_weighted: Decimal
    sustain_weighted: Decimal
    chassis_weighted: Decimal
    completion_gold_weighted: Decimal
    blockers: frozenset[str]
    all_core_contact: bool
    all_core_chassis: bool
    all_core_item_ready: bool
    heartsteel_proc_count: int
    total_gold: int


@dataclass(frozen=True)
class _StageRecord:
    """Hold the per-core stage outcome reused by every path with the same prefix."""

    opponent_hp_lost: Decimal
    actor_end_hp: Decimal
    actor_survival_ms: int
    uptime: Decimal
    lane_recovered: Decimal
    mixed_ehp: Decimal
    blockers: frozenset[str]
    contact: bool
    chassis_ready: bool
    item_ready: bool
    heartsteel_proc_count: int


def _prefix_cache_key(path: tuple[int, ...], core: int) -> tuple[tuple[int, ...], int, int]:
    """Identify the stage outcome a build prefix produces at one core.

    Stage metrics aggregate item stats, so purchase order is irrelevant except for
    Heartsteel, whose stack count depends on when it was bought and on the items
    owned at that moment. Heartsteel prefixes therefore keep their original order.

    :param path: Actor item path through the current core.
    :param core: Current one-based core index.
    :return: Cache key covering the prefix identity and the core index.
    """
    if 3084 in path:
        return path, path.index(3084) + 1, core
    return tuple(sorted(path)), 0, core


def _stage_record(
    engine: Any,
    request: Any,
    actor_cog: Any,
    opponent_cog: Any,
    path: tuple[int, ...],
    core: int,
    cache: dict[tuple[tuple[int, ...], int, int], _StageRecord],
) -> _StageRecord:
    """Evaluate one core stage, reusing an earlier result for an equivalent prefix.

    :param engine: Matchup engine providing two-sided evaluation.
    :param request: Original matchup request.
    :param actor_cog: Actor Cog receiving the recommendation.
    :param opponent_cog: Opponent Cog supplying the target build.
    :param path: Actor item path through the current core.
    :param core: Current one-based core index.
    :param cache: Mutable store of stage outcomes keyed by prefix identity.
    :return: Stage outcome for this prefix at this core.
    """
    from lol_build.application.matchup import MatchupRequest, OpponentSpec

    key = _prefix_cache_key(path, core)
    cached = cache.get(key)
    if cached is not None:
        return cached
    heartsteel_count, heartsteel_health = _heartsteel_bonus_health(engine, request, path, core)
    evaluation = engine.evaluate(
        MatchupRequest(
            actor_cog.champion_key,
            opponent_cog.champion_key,
            level=request.level,
            duration_ms=request.duration_ms,
            horizon_ms=request.horizon_ms,
            actor_item_ids=path,
            opponent_item_ids=request.opponent_item_ids[:core],
            actor_bonus_health=heartsteel_health,
            additional_opponents=tuple(
                OpponentSpec(spec.champion, spec.item_ids[:core], spec.bonus_health)
                for spec in request.additional_opponents
            ),
            allies=tuple(
                OpponentSpec(spec.champion, spec.item_ids[:core], spec.bonus_health)
                for spec in request.allies
            ),
            team_arrival_distance=request.team_arrival_distance,
            team_arrival_spends_dash=request.team_arrival_spends_dash,
        )
    )
    stage = _stage_noncombat_metrics(
        engine,
        request,
        path,
        request.opponent_item_ids[:core],
        heartsteel_health,
        core,
        getattr(request, "active_duty_policy", _DEFAULT_ACTIVE_DUTY_POLICY),
        getattr(request, "pursuit_target_policy", _DEFAULT_PURSUIT_TARGET_POLICY),
    )
    record = _StageRecord(
        evaluation.timeline.actor_damage_dealt
        if request.allies
        else evaluation.opposing_side_hp_lost,
        evaluation.timeline.actor_at_end.current_hp,
        evaluation.timeline.actor_survival_ms,
        stage["uptime"],
        stage["lane_recovered"],
        stage["mixed_ehp"],
        frozenset(evaluation.blockers) | frozenset(stage["blockers"]),
        stage["contact"],
        stage["chassis_ready"],
        stage["item_ready"],
        heartsteel_count,
    )
    cache[key] = record
    return record


_WORKER: dict[str, Any] = {}


def _init_stage_worker(root: Any, request: Any) -> None:
    """Build one engine per worker process so tasks stay small to send.

    :param root: Project root holding the locked patch data.
    :param request: Matchup request shared by every task in this run.
    :return: None.
    """
    from lol_build.application.matchup import MatchupEngine

    engine = MatchupEngine(root)
    _WORKER["engine"] = engine
    _WORKER["request"] = request
    _WORKER["actor_cog"] = engine.registry.require_cog(request.actor)
    _WORKER["opponent_cog"] = engine.registry.require_cog(request.opponent)


def _evaluate_stage_task(
    task: tuple[tuple[int, ...], int],
) -> tuple[tuple[tuple[int, ...], int, int], _StageRecord]:
    """Evaluate one build prefix inside a worker process.

    :param task: Build prefix and the core index it is evaluated at.
    :return: Cache key and the stage outcome it identifies.
    """
    path, core = task
    record = _stage_record(
        _WORKER["engine"],
        _WORKER["request"],
        _WORKER["actor_cog"],
        _WORKER["opponent_cog"],
        path,
        core,
        {},
    )
    return _prefix_cache_key(path, core), record


@contextmanager
def _stage_pool(
    workers: int,
    root: Any,
    request: Any,
    progress: ProgressCallback | None,
) -> Iterator[Any]:
    """Provide one worker pool for the whole search, or ``None`` to stay inline.

    Prefilling is an optimization: the sequential pass computes whatever the
    workers did not, so a pool that cannot start costs time rather than
    correctness. That is reported instead of raised.

    :param workers: Requested worker processes; one keeps everything inline.
    :param root: Project root each worker loads its engine from.
    :param request: Matchup request shared by every task.
    :param progress: Optional callback receiving live calculation milestones.
    :return: Context yielding a live pool or ``None``.
    """
    if workers <= 1:
        yield None
        return
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    pool = None
    try:
        pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_stage_worker,
            initargs=(root, request),
        )
        yield pool
    except (BrokenProcessPool, OSError) as error:
        report_progress(
            progress,
            f"병렬 계산을 시작하지 못해 단일 프로세스로 계속합니다 · {type(error).__name__}",
        )
        yield None
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _prefill_stage_cache(
    legal: list[tuple[_BeamState, tuple[int, ...], int]],
    core: int,
    cache: dict[tuple[tuple[int, ...], int, int], _StageRecord],
    *,
    pool: Any,
    workers: int,
) -> None:
    """Evaluate this core's missing stage outcomes across worker processes.

    Only distinct prefixes are dispatched, and every result is stored before the
    sequential pass runs, so the search order and its results are unchanged by
    how many workers were used.

    :param legal: Candidate expansions surviving this core's legality filters.
    :param core: Current one-based core index.
    :param cache: Stage cache filled in place.
    :param pool: Live worker pool, or ``None`` to evaluate in this process.
    :param workers: Worker count used to size batches.
    :return: None.
    """
    if pool is None:
        return
    pending: dict[tuple[tuple[int, ...], int, int], tuple[int, ...]] = {}
    for _, path, _ in legal:
        key = _prefix_cache_key(path, core)
        if key not in cache and key not in pending:
            pending[key] = path
    if len(pending) < workers * 2:
        return
    tasks = [(path, core) for path in pending.values()]
    for key, record in pool.map(
        _evaluate_stage_task, tasks, chunksize=max(1, len(tasks) // (workers * 8))
    ):
        cache[key] = record


def _path_is_legal_beam(
    path: tuple[int, ...],
    *,
    item_by_id: Mapping[int, Mapping[str, Any]],
    budgets: tuple[int, int, int],
) -> bool:
    """Reapply the beam expansion's hard legality filters to one full item path.

    Purchase-exclusive-group conflicts only ever add up as items are added, so
    checking the full path implies every shorter prefix is legal too; budget
    is checked at each core separately since it accumulates independently per
    core. Repeated ``same_passive``/``shared_cooldown`` groups are legal to
    purchase but structurally unscoreable (see
    :func:`~lol_build.application.item_combat.duplicate_group_blockers`), so
    they are excluded here for the same reason the main scan excludes them.

    :param path: Full ordered candidate path.
    :param item_by_id: Loaded item documents keyed by Riot identifier.
    :param budgets: Cumulative gold ceilings at one, two, and three cores.
    :return: Whether this exact path would have survived the main beam expansion.
    """

    running_gold = 0
    for core, item_id in enumerate(path, start=1):
        running_gold += item_by_id[item_id]["cost"]["total"]
        if running_gold > budgets[core - 1]:
            return False
    boots = sum(item_by_id[item_id]["groups"]["purchase_limit"] == "boots" for item_id in path)
    if boots > 1:
        return False
    items = tuple(item_by_id[item_id] for item_id in path)
    if duplicate_group_blockers(items):
        return False
    groups = [item["groups"] for item in items]
    exclusive_groups = [group for value in groups for group in value.get("purchase_exclusive", ())]
    return len(exclusive_groups) == len(set(exclusive_groups))


def _evaluate_ordered_path_state(
    engine: Any,
    request: Any,
    actor_cog: Any,
    opponent_cog: Any,
    path: tuple[int, ...],
    prefix_cache: dict[tuple[tuple[int, ...], int, int], _StageRecord],
    stage_weights: tuple[int, int, int],
    item_by_id: Mapping[int, Mapping[str, Any]],
) -> _BeamState:
    """Weight one already-legal item path's metrics across its build progression.

    Mirrors the main beam expansion's per-core accumulation for a single fixed
    path instead of every legal expansion at that core, so an ablation
    candidate scores exactly as the main search would have scored it.

    :param engine: Matchup engine providing locked items and two-sided evaluation.
    :param request: Original matchup request.
    :param actor_cog: Actor Cog receiving the recommendation.
    :param opponent_cog: Opponent Cog supplying the target build.
    :param path: Full ordered candidate path.
    :param prefix_cache: Memoized per-prefix stage outcomes, shared and mutated in place.
    :param stage_weights: Integer importance weights for each core timing.
    :param item_by_id: Loaded item documents keyed by Riot identifier.
    :return: Weighted beam state equivalent to one produced by the main search.
    """

    state = _BeamState(
        (),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        frozenset(),
        True,
        True,
        True,
        0,
        0,
    )
    running_gold = 0
    for core in range(1, len(path) + 1):
        prefix = path[:core]
        running_gold += item_by_id[path[core - 1]]["cost"]["total"]
        record = _stage_record(engine, request, actor_cog, opponent_cog, prefix, core, prefix_cache)
        weight = Decimal(stage_weights[core - 1])
        state = _BeamState(
            prefix,
            state.damage_weighted + record.opponent_hp_lost * record.uptime * weight,
            state.survival_weighted + record.actor_end_hp * weight,
            state.survival_ms_weighted + Decimal(record.actor_survival_ms) * weight,
            state.engagement_weighted + record.uptime * weight,
            state.sustain_weighted + record.lane_recovered * weight,
            state.chassis_weighted + record.mixed_ehp * weight,
            state.completion_gold_weighted + Decimal(running_gold) * weight,
            state.blockers | record.blockers,
            state.all_core_contact and record.contact,
            state.all_core_chassis and record.chassis_ready,
            state.all_core_item_ready and record.item_ready,
            record.heartsteel_proc_count,
            running_gold,
        )
    return state


def _slot_runner_up_beam_candidate(
    path: tuple[int, ...],
    slot: int,
    *,
    engine: Any,
    request: Any,
    actor_cog: Any,
    opponent_cog: Any,
    items: tuple[Mapping[str, Any], ...],
    item_by_id: Mapping[int, Mapping[str, Any]],
    budgets: tuple[int, int, int],
    stage_weights: tuple[int, int, int],
    prefix_cache: dict[tuple[tuple[int, ...], int, int], _StageRecord],
    pool: Any,
    workers: int,
    denominator: Decimal,
    gate: Callable[[_BeamState, Mapping[str, Decimal]], bool],
    sort_key: Callable[[tuple[_BeamState, Mapping[str, Decimal]]], Any],
) -> tuple[
    _BeamState | None,
    Mapping[str, Decimal] | None,
    int,
    int,
    _BeamState | None,
    Mapping[str, Decimal] | None,
]:
    """Find the best legal, gate-passing alternative for one slot of a winning path.

    Reuses the exact legality rules and per-path evaluation the main search
    used, so the reported alternative is a real competitor the search could
    actually have chosen, not an approximation.

    :param path: The selected branch's winning ordered item ids.
    :param slot: Zero-based position within ``path`` to vary.
    :param engine: Matchup engine providing locked items and two-sided evaluation.
    :param request: Original matchup request.
    :param actor_cog: Actor Cog receiving the recommendation.
    :param opponent_cog: Opponent Cog supplying the target build.
    :param items: Full legal candidate item pool the main search drew from.
    :param item_by_id: Loaded item documents keyed by Riot identifier.
    :param budgets: Cumulative gold ceilings at one, two, and three cores.
    :param stage_weights: Integer importance weights for each core timing.
    :param prefix_cache: Memoized per-prefix stage outcomes, shared and mutated in place.
    :param pool: Live worker pool, or ``None`` to evaluate in this process.
    :param workers: Worker count used to size prefill batches.
    :param denominator: Sum of stage weights used for metric normalization.
    :param gate: Branch-specific admissibility predicate over a scored candidate.
    :param sort_key: Branch-specific ranking key; the minimum wins.
    :return: The best gate-passing alternative state and metrics (or ``None``),
        how many passed the branch's gate, how many were legal before that
        gate, and — only when no candidate passed the gate but at least one
        was legal — the single best gate-*failing* candidate (ranked the same
        way, gate ignored) and its metrics, so a caller can explain what was
        actually closest instead of reporting a bare "no alternative".
    """

    fixed_ids = {item_id for index, item_id in enumerate(path) if index != slot}
    candidate_paths: list[tuple[int, ...]] = []
    for item in items:
        item_id = item["id"]
        if item_id == path[slot] or item_id in fixed_ids:
            continue
        if actor_cog.item_candidate_blocker(item) is not None:
            continue
        candidate_path = tuple(
            item_id if index == slot else path[index] for index in range(len(path))
        )
        if _path_is_legal_beam(candidate_path, item_by_id=item_by_id, budgets=budgets):
            candidate_paths.append(candidate_path)
    if not candidate_paths:
        return None, None, 0, 0, None, None
    for core in range(1, len(path) + 1):
        legal_like = [(None, candidate_path[:core], 0) for candidate_path in candidate_paths]
        _prefill_stage_cache(legal_like, core, prefix_cache, pool=pool, workers=workers)
    all_scored: list[tuple[_BeamState, Mapping[str, Decimal]]] = []
    scored: list[tuple[_BeamState, Mapping[str, Decimal]]] = []
    for candidate_path in candidate_paths:
        state = _evaluate_ordered_path_state(
            engine,
            request,
            actor_cog,
            opponent_cog,
            candidate_path,
            prefix_cache,
            stage_weights,
            item_by_id,
        )
        metrics = _beam_metrics(state, denominator)
        all_scored.append((state, metrics))
        if gate(state, metrics):
            scored.append((state, metrics))
    if not scored:
        excluded_state, excluded_metrics = min(all_scored, key=sort_key)
        return None, None, 0, len(candidate_paths), excluded_state, excluded_metrics
    best_state, best_metrics = min(scored, key=sort_key)
    return best_state, best_metrics, len(scored), len(candidate_paths), None, None


def _beam_metrics(state: _BeamState, denominator: Decimal) -> dict[str, Decimal]:
    """Materialize user-visible metrics from one weighted beam state.

    :param state: Completed three-core beam state.
    :param denominator: Sum of stage weights used for normalization.
    :return: Named metric vector used by branch selection.
    """
    return {
        "DAMAGE_TOTAL_8S": state.damage_weighted / denominator,
        "ACTOR_END_HP_8S": state.survival_weighted / denominator,
        "ACTOR_SURVIVAL_MS_8S": state.survival_ms_weighted / denominator,
        "ENGAGE_COMBAT_UPTIME_FRACTION": state.engagement_weighted / denominator,
        "LANE_RECOVERED_HP_30S": state.sustain_weighted / denominator,
        "MIXED_EFFECTIVE_HEALTH": state.chassis_weighted / denominator,
        "CORE_COMPLETION_GOLD_WEIGHTED": state.completion_gold_weighted / denominator,
        "ALL_CORE_ENGAGE_READY": Decimal(state.all_core_contact),
        "ALL_CORE_CHASSIS_READY": Decimal(state.all_core_chassis),
        "ALL_CORE_ITEM_PASSIVES_READY": Decimal(state.all_core_item_ready),
        "HEARTSTEEL_PROC_COUNT": Decimal(state.heartsteel_proc_count),
        "TOTAL_GOLD": Decimal(state.total_gold),
        "OCCUPIED_SLOTS": Decimal(3),
    }


def _choose_state(
    pool: list[_BeamState],
    priorities: tuple[str, ...],
    metric_by_path: dict[tuple[int, ...], dict[str, Decimal]],
) -> _BeamState:
    """Choose one state lexicographically from an already admissible pool.

    :param pool: Candidate states allowed by the branch's hard gates.
    :param priorities: Descending metric priority order.
    :param metric_by_path: Materialized metrics keyed by ordered item path.
    :return: Deterministically selected state.
    """
    return min(
        pool,
        key=lambda state: (
            *(-metric_by_path[state.item_ids][metric] for metric in priorities),
            metric_by_path[state.item_ids]["CORE_COMPLETION_GOLD_WEIGHTED"],
            state.total_gold,
            state.item_ids,
        ),
    )


def _runner_up(
    pool: list[_BeamState],
    selected: _BeamState,
    priorities: tuple[str, ...],
    metric_by_path: dict[tuple[int, ...], dict[str, Decimal]],
) -> _BeamState | None:
    """Choose the best remaining state under the selected branch policy.

    :param pool: Candidate states eligible for the branch.
    :param selected: Winning state excluded from comparison.
    :param priorities: Descending metric priority order.
    :param metric_by_path: Materialized metrics keyed by ordered item path.
    :return: Runner-up state, or ``None`` when no alternative exists.
    """

    alternatives = [state for state in pool if state.item_ids != selected.item_ids]
    return _choose_state(alternatives, priorities, metric_by_path) if alternatives else None


def _satisfied_constraints(state: _BeamState) -> tuple[str, ...]:
    """Expose readiness gates actually satisfied by a selected beam state.

    :param state: Selected build-search frontier state.
    :return: Stable constraint codes supported by accumulated stage results.
    """

    constraints = []
    if state.all_core_contact:
        constraints.append("ALL_CORE_ENGAGE_READY")
    if state.all_core_chassis:
        constraints.append("ALL_CORE_CHASSIS_READY")
    if state.all_core_item_ready:
        constraints.append("ALL_CORE_ITEM_PASSIVES_READY")
    return tuple(constraints)


def generic_cog_build_preview(
    engine: Any,
    request: Any,
    *,
    workers: int | None = None,
    budgets: tuple[int, int, int] = (4000, 7000, 10000),
    stage_weights: tuple[int, int, int] = (7, 7, 6),
    defense_max_primary_loss_fraction: Decimal = Decimal("0.20"),
    progress: ProgressCallback | None = None,
) -> CogBuildPreview:
    """Search every ordered three-core build using the actor Cog's event model.

    Every legal three-item ordered path is evaluated exhaustively; nothing is
    pruned between cores. An earlier version retained only a bounded frontier
    of "promising" states after each core, which is fast but can permanently
    discard a prefix that only becomes optimal once completed — confirmed in
    practice (a Darius-versus-Garen defense build was misranked because its
    best second item never looked competitive as a lone first item). Repeated
    (state, item) prefixes are still deduplicated through ``prefix_cache`` and
    evaluated in parallel via the worker pool, so the exhaustive scan costs
    roughly what the old frontier scan did per *unique* prefix — it just no
    longer throws prefixes away before their continuations are tried.

    :param engine: Matchup engine providing locked items and two-sided evaluation.
    :param request: Matchup request whose actor receives the recommendation.
    :param workers: Worker processes used to evaluate distinct build prefixes.
        ``None`` uses every available core, and ``1`` keeps the search in this
        process. Results do not depend on this value.
    :param budgets: Cumulative gold ceilings at one, two, and three cores.
    :param stage_weights: Integer importance weights for each core timing.
    :param defense_max_primary_loss_fraction: Largest damage loss accepted by defense.
    :param progress: Optional callback receiving live calculation milestones.
    :return: Three deterministic branches with blockers and scope metadata.
    :raises ValueError: If no legal core exists.
    """
    workers = (os.cpu_count() or 1) if workers is None else max(1, workers)
    root = engine.root
    actor_cog = engine.registry.require_cog(request.actor)
    opponent_cog = engine.registry.require_cog(request.opponent)
    items = tuple(engine.complete_items)
    report_progress(progress, f"2/7 후보 아이템 풀 준비 완료 · {len(items)}개")
    item_by_id = {item["id"]: item for item in items}
    states = [
        _BeamState(
            (),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            frozenset(),
            True,
            True,
            True,
            0,
            0,
        )
    ]
    evaluated = 0
    excluded_duplicate_group = False
    prefix_cache: dict[tuple[tuple[int, ...], int, int], _StageRecord] = {}
    with _stage_pool(workers, root, request, progress) as pool:
        for core in range(1, 4):
            expanded: list[_BeamState] = []
            legal: list[tuple[_BeamState, tuple[int, ...], int]] = []
            for state in states:
                for item in items:
                    if actor_cog.item_candidate_blocker(item) is not None:
                        continue
                    item_id = item["id"]
                    if item_id in state.item_ids:
                        continue
                    path = (*state.item_ids, item_id)
                    total_gold = state.total_gold + item["cost"]["total"]
                    if total_gold > budgets[core - 1]:
                        continue
                    boots = sum(
                        item_by_id[value]["groups"]["purchase_limit"] == "boots" for value in path
                    )
                    if boots > 1:
                        continue
                    path_items = tuple(item_by_id[value] for value in path)
                    if duplicate_group_blockers(path_items):
                        excluded_duplicate_group = True
                        continue
                    groups = [item["groups"] for item in path_items]
                    exclusive_groups = [
                        group for value in groups for group in value.get("purchase_exclusive", ())
                    ]
                    if len(exclusive_groups) != len(set(exclusive_groups)):
                        continue
                    legal.append((state, path, total_gold))
            _prefill_stage_cache(legal, core, prefix_cache, pool=pool, workers=workers)
            for state, path, total_gold in legal:
                record = _stage_record(
                    engine, request, actor_cog, opponent_cog, path, core, prefix_cache
                )
                weight = Decimal(stage_weights[core - 1])
                expanded.append(
                    _BeamState(
                        path,
                        state.damage_weighted + record.opponent_hp_lost * record.uptime * weight,
                        state.survival_weighted + record.actor_end_hp * weight,
                        state.survival_ms_weighted + Decimal(record.actor_survival_ms) * weight,
                        state.engagement_weighted + record.uptime * weight,
                        state.sustain_weighted + record.lane_recovered * weight,
                        state.chassis_weighted + record.mixed_ehp * weight,
                        state.completion_gold_weighted + Decimal(total_gold) * weight,
                        state.blockers | record.blockers,
                        state.all_core_contact and record.contact,
                        state.all_core_chassis and record.chassis_ready,
                        state.all_core_item_ready and record.item_ready,
                        record.heartsteel_proc_count,
                        total_gold,
                    )
                )
                evaluated += 1
            if not expanded:
                raise ValueError(f"no legal candidates at core {core}")
            states = expanded
            report_progress(
                progress,
                f"{core + 2}/7 {core}코어 후보 평가 완료 · 누적 {evaluated:,}개 / "
                f"경로 {len(states):,}개 / 실계산 {len(prefix_cache):,}개",
            )
    denominator = Decimal(sum(stage_weights))

    metric_by_path = {state.item_ids: _beam_metrics(state, denominator) for state in states}
    best_damage = max(value["DAMAGE_TOTAL_8S"] for value in metric_by_path.values())

    offense = _choose_state(
        states,
        ("DAMAGE_TOTAL_8S", "ENGAGE_COMBAT_UPTIME_FRACTION"),
        metric_by_path,
    )
    chassis_states = [
        state
        for state in states
        if state.all_core_chassis and state.all_core_contact and state.all_core_item_ready
    ]
    selection_blockers: set[str] = set()
    if request.additional_opponents:
        selection_blockers.add("TEAM_ENCOUNTER_CHASSIS_METRICS_USE_PRIMARY_OPPONENT_ONLY")
    if request.allies:
        selection_blockers.add("DAMAGE_METRIC_ISOLATES_ACTOR_CONTRIBUTION")
    if excluded_duplicate_group:
        selection_blockers.add("SAME_PASSIVE_OR_SHARED_COOLDOWN_DUPLICATES_EXCLUDED")
    if chassis_states:
        default_pool = list(chassis_states)
        defense_chassis_pool = chassis_states
    else:
        selection_blockers.add("NO_CANDIDATE_MEETS_ALL_CORE_CHASSIS_FLOORS")
        default_pool = list(states)
        defense_chassis_pool = states
    defense_damage_gated_pool = [
        state
        for state in defense_chassis_pool
        if defense_candidate_is_feasible(
            metric_by_path[state.item_ids],
            primary_metric="DAMAGE_TOTAL_8S",
            best_primary=best_damage,
            maximum_primary_loss_fraction=defense_max_primary_loss_fraction,
            all_core_engage_ready=state.all_core_contact,
            all_core_chassis_ready=state.all_core_chassis,
            all_core_item_passives_ready=state.all_core_item_ready,
        )
    ]
    if defense_damage_gated_pool:
        defense_pool = defense_damage_gated_pool
    else:
        selection_blockers.add("NO_CANDIDATE_MEETS_DEFENSE_DAMAGE_FLOOR")
        defense_pool = list(defense_chassis_pool)
    # The chassis/EHP-ratio check above is the gate — "can this build start and
    # survive the fight at all?" Once through it, DEFAULT ranks exactly like
    # OFFENSE (damage first): a gate is not a weighted blend of damage and
    # defense, so surviving candidates are not further optimized for survival.
    default = _choose_state(
        default_pool,
        ("DAMAGE_TOTAL_8S", "MIXED_EFFECTIVE_HEALTH"),
        metric_by_path,
    )
    # Mirrors DEFAULT's own fallback: a branch that can vanish outright instead
    # of degrading (no candidate at all instead of the best available one) is a
    # worse failure than ranking without a gate the search proved unreachable —
    # confirmed in practice (a melee actor chasing a kiting target can fail
    # every chassis or damage-floor candidate, dropping DEFENSE entirely; see
    # TASKS.md). Both tiers fall back to the wider pool with a blocker instead.
    defense = _choose_state(
        defense_pool,
        (
            "ACTOR_SURVIVAL_MS_8S",
            "MIXED_EFFECTIVE_HEALTH",
            "LANE_RECOVERED_HP_30S",
            "ACTOR_END_HP_8S",
        ),
        metric_by_path,
    )
    report_progress(progress, "6/7 균형·공격·방어 분기 선택 중")
    chosen = {
        BranchId.DEFAULT: default,
        BranchId.OFFENSE: offense,
        BranchId.DEFENSE: defense,
    }
    branch_pools = {
        BranchId.DEFAULT: default_pool,
        BranchId.OFFENSE: states,
        BranchId.DEFENSE: defense_pool,
    }
    branch_priorities = {
        BranchId.DEFAULT: ("DAMAGE_TOTAL_8S", "MIXED_EFFECTIVE_HEALTH"),
        BranchId.OFFENSE: ("DAMAGE_TOTAL_8S", "ENGAGE_COMBAT_UPTIME_FRACTION"),
        BranchId.DEFENSE: (
            "ACTOR_SURVIVAL_MS_8S",
            "MIXED_EFFECTIVE_HEALTH",
            "LANE_RECOVERED_HP_30S",
            "ACTOR_END_HP_8S",
        ),
    }
    branch_reasons = {
        BranchId.DEFAULT: (
            "BALANCED_CHASSIS_GATED_DAMAGE_PRIORITY"
            if chassis_states
            else "BALANCED_FALLBACK_NO_FULL_CHASSIS"
        ),
        BranchId.OFFENSE: "OFFENSE_DAMAGE_PRIORITY",
        BranchId.DEFENSE: (
            "DEFENSE_DURABILITY_WITH_DAMAGE_FLOOR"
            if defense_damage_gated_pool
            else (
                "DEFENSE_FALLBACK_NO_FULL_CHASSIS"
                if not chassis_states
                else "DEFENSE_FALLBACK_NO_DAMAGE_FLOOR_MET"
            )
        ),
    }

    def _default_gate(state: _BeamState, metrics: Mapping[str, Decimal]) -> bool:
        """Reapply the default branch's chassis-and-EHP-ratio gate.

        The gate only asks whether the build can start and survive the fight;
        it is not a weighted blend of damage and defense, so it never checks
        damage. See :func:`generic_cog_build_preview` for why.

        :param state: Evaluated build state under comparison.
        :param metrics: That state's materialized metric vector.
        :return: Whether ``state`` would remain in the default candidate pool.
        """

        if chassis_states:
            return state.all_core_chassis and state.all_core_contact and state.all_core_item_ready
        return True

    def _defense_gate(state: _BeamState, metrics: Mapping[str, Decimal]) -> bool:
        """Reapply the defense branch's chassis-and-feasibility gate.

        Mirrors the same two-tier fallback used to build ``defense_pool``: a
        tier only gates candidates when the main search proved at least one
        candidate could clear it, so an ablation alternative is judged by
        exactly the rule that selected the winner it is being compared to.

        :param state: Evaluated build state under comparison.
        :param metrics: That state's materialized metric vector.
        :return: Whether ``state`` would remain in the defense candidate pool.
        """

        if chassis_states and not (
            state.all_core_chassis and state.all_core_contact and state.all_core_item_ready
        ):
            return False
        if not defense_damage_gated_pool:
            return True
        return defense_candidate_is_feasible(
            metrics,
            primary_metric="DAMAGE_TOTAL_8S",
            best_primary=best_damage,
            maximum_primary_loss_fraction=defense_max_primary_loss_fraction,
            all_core_engage_ready=state.all_core_contact,
            all_core_chassis_ready=state.all_core_chassis,
            all_core_item_passives_ready=state.all_core_item_ready,
        )

    branch_ablation_gate: dict[BranchId, Callable[[_BeamState, Mapping[str, Decimal]], bool]] = {
        BranchId.DEFAULT: _default_gate,
        BranchId.OFFENSE: lambda state, metrics: True,
        BranchId.DEFENSE: _defense_gate,
    }

    def _slot_exclusion_reasons(
        branch: BranchId, state: _BeamState, metrics: Mapping[str, Decimal]
    ) -> tuple[str, ...]:
        """Name exactly which gate condition kept a slot's best legal item out.

        Mirrors ``_default_gate``/``_defense_gate``'s own two-tier fallback so
        a reason is only reported for a tier the branch actually enforced —
        a chassis complaint would be misleading once that tier already
        degraded to "every legal candidate is eligible".

        :param branch: Branch the excluded candidate was evaluated against.
        :param state: The excluded candidate's evaluated beam state.
        :param metrics: The excluded candidate's materialized metric vector.
        :return: Ordered gate-failure codes; empty if nothing applies.
        """

        if branch is BranchId.OFFENSE:
            return ()
        reasons: list[str] = []
        if chassis_states:
            if not state.all_core_contact:
                reasons.append("ALL_CORE_ENGAGE_READY_NOT_MET")
            if not state.all_core_chassis:
                reasons.append("ALL_CORE_CHASSIS_READY_NOT_MET")
            if not state.all_core_item_ready:
                reasons.append("ALL_CORE_ITEM_PASSIVES_READY_NOT_MET")
        if (
            branch is BranchId.DEFENSE
            and not reasons
            and defense_damage_gated_pool
            and not defense_candidate_is_feasible(
                metrics,
                primary_metric="DAMAGE_TOTAL_8S",
                best_primary=best_damage,
                maximum_primary_loss_fraction=defense_max_primary_loss_fraction,
                all_core_engage_ready=state.all_core_contact,
                all_core_chassis_ready=state.all_core_chassis,
                all_core_item_passives_ready=state.all_core_item_ready,
            )
        ):
            reasons.append("DEFENSE_DAMAGE_FLOOR_NOT_MET")
        return tuple(reasons)

    def _slot_sort_key(
        priorities: tuple[str, ...],
    ) -> Callable[[tuple[_BeamState, Mapping[str, Decimal]]], Any]:
        """Build the ablation ranking key matching ``_choose_state``'s order.

        :param priorities: Metrics the branch's own selection rule ranks by.
        :return: Ascending sort key over ``(state, metrics)`` pairs.
        """

        def key(pair: tuple[_BeamState, Mapping[str, Decimal]]) -> Any:
            """Rank one ablation candidate by the branch's metric priority order.

            :param pair: Evaluated state and its materialized metric vector.
            :return: Ascending sort key; the minimum across candidates wins.
            """

            state, metrics = pair
            return (
                *(-metrics[metric] for metric in priorities),
                metrics["CORE_COMPLETION_GOLD_WEIGHTED"],
                state.total_gold,
                state.item_ids,
            )

        return key

    explanations = {}
    with _stage_pool(workers, root, request, progress) as ablation_pool:
        for branch, state in chosen.items():
            priorities = branch_priorities[branch]
            reference = _runner_up(branch_pools[branch], state, priorities, metric_by_path)
            constraints = list(_satisfied_constraints(state))
            if branch is BranchId.DEFENSE and defense_damage_gated_pool:
                constraints.append("PRIMARY_DAMAGE_FLOOR_PASSED")
            slot_runner_ups = []
            for slot in range(len(state.item_ids)):
                (
                    runner_up_state,
                    runner_up_metrics,
                    alternative_count,
                    legal_alternative_count,
                    excluded_state,
                    excluded_metrics,
                ) = _slot_runner_up_beam_candidate(
                    state.item_ids,
                    slot,
                    engine=engine,
                    request=request,
                    actor_cog=actor_cog,
                    opponent_cog=opponent_cog,
                    items=items,
                    item_by_id=item_by_id,
                    budgets=budgets,
                    stage_weights=stage_weights,
                    prefix_cache=prefix_cache,
                    pool=ablation_pool,
                    workers=workers,
                    denominator=denominator,
                    gate=branch_ablation_gate[branch],
                    sort_key=_slot_sort_key(priorities),
                )
                slot_runner_ups.append(
                    build_slot_runner_up(
                        priority_metrics=priorities,
                        selected_metrics=metric_by_path[state.item_ids],
                        runner_up_item_id=(
                            runner_up_state.item_ids[slot] if runner_up_state is not None else None
                        ),
                        runner_up_metrics=runner_up_metrics,
                        alternative_count=alternative_count,
                        legal_alternative_count=legal_alternative_count,
                        excluded_item_id=(
                            excluded_state.item_ids[slot] if excluded_state is not None else None
                        ),
                        excluded_reason_codes=(
                            _slot_exclusion_reasons(branch, excluded_state, excluded_metrics)
                            if excluded_state is not None and excluded_metrics is not None
                            else ()
                        ),
                        excluded_metrics=excluded_metrics,
                    )
                )
            explanations[branch] = build_explanation(
                policy_id=f"generic_{branch.value.lower()}_selection_v1",
                reason_codes=(branch_reasons[branch],),
                satisfied_constraints=tuple(constraints),
                priority_metrics=priorities,
                selected_item_ids=state.item_ids,
                selected_metrics=metric_by_path[state.item_ids],
                items_by_id=item_by_id,
                comparison_kind="FINALIST_RUNNER_UP" if reference is not None else None,
                comparison_item_ids=reference.item_ids if reference is not None else (),
                comparison_metrics=(
                    metric_by_path[reference.item_ids] if reference is not None else None
                ),
                slot_runner_ups=tuple(slot_runner_ups),
            )
    blockers = tuple(
        sorted(
            set().union(*(state.blockers for state in chosen.values()))
            | selection_blockers
            | {
                "GENERIC_BUILD_BEAM_SEARCH_UNVERIFIED",
                "GENERIC_BUILD_BRANCH_DAMAGE_FLOORS_UNVERIFIED",
                "GENERIC_ENGAGEMENT_SCENARIO_UNVERIFIED",
                "GENERIC_LANE_SUSTAIN_SCENARIO_UNVERIFIED",
                "GENERIC_HEARTSTEEL_CADENCE_UNVERIFIED",
            }
        )
    )
    result = CogBuildPreview(
        RecommendationStatus.INSUFFICIENT_EVIDENCE,
        RecommendationState(
            OutcomeStatus.FOUND,
            VerificationStatus.INSUFFICIENT_VERIFICATION,
            ScopeStatus.IN_SCOPE,
        ),
        pregame_assumptions(request.level, "USER_SPECIFIED"),
        RecommendationScope(
            "generic_level13_duel_8s_v1",
            "16.17.1",
            actor_cog.champion_id,
            request.duration_ms,
            1,
            3,
        ),
        "COG_GENERIC_SYNTHETIC_NON_RELEASE",
        False,
        actor_cog.qualified_name,
        opponent_cog.qualified_name,
        {
            branch: CogPreviewBranch(
                branch,
                state.item_ids,
                metric_by_path[state.item_ids],
                explanations[branch],
            )
            for branch, state in chosen.items()
        },
        evaluated,
        blockers,
    )
    report_progress(progress, "6/7 분기 선택·선정 근거·blocker 결합 완료")
    return result


def _heartsteel_bonus_health(
    engine: Any,
    request: Any,
    path: tuple[int, ...],
    core: int,
) -> tuple[int, Decimal]:
    """Estimate Heartsteel stacks from the core completion timestamp.

    :param engine: Matchup engine used for participant snapshots.
    :param request: Matchup request providing opponent items and level.
    :param path: Actor item path through the current core.
    :param core: Current one-based core index.
    :return: Proc count and accumulated bonus health.
    """
    if 3084 not in path:
        return 0, Decimal(0)
    position = path.index(3084) + 1
    completion = {1: 600_000, 2: 1_020_000, 3: 1_440_000}
    evaluation = {1: 1_020_000, 2: 1_440_000, 3: 1_800_000}
    actor_cog = engine.registry.require_cog(request.actor)
    opponent_cog = engine.registry.require_cog(request.opponent)
    purchase_items = path[:position]
    purchase_snapshot = actor_cog.snapshot(
        level=request.level,
        item_stats=engine._item_stats(purchase_items, request.level, actor_cog),
    )
    opponent_snapshot = opponent_cog.snapshot(
        level=request.level,
        item_stats=engine._item_stats(
            request.opponent_item_ids[:core], request.level, opponent_cog
        ),
    )
    result = simulate_heartsteel_progression(
        purchase_ms=completion[position],
        evaluation_ms=evaluation[core],
        first_proc_delay_ms=30_000,
        proc_interval_ms=60_000,
        base_max_health_at_purchase=purchase_snapshot.max_hp,
        target_armor=opponent_snapshot.armor,
    )
    return result.proc_count, result.bonus_health


def _fleeing_move_speed(
    actor_attack_range: Decimal,
    target_attack_range: Decimal,
    target_move_speed: Decimal,
    policy: str,
) -> Decimal:
    """Return the speed the target retreats at under one pursuit policy.

    :param actor_attack_range: Reach of the pursuing participant.
    :param target_attack_range: Reach of the participant being pursued.
    :param target_move_speed: Speed the target would flee at.
    :param policy: One of :data:`PURSUIT_TARGET_POLICIES`.
    :return: Retreat speed fed to the pursuit benchmark.
    :raises ValueError: If the policy is not recognized.
    """
    if policy == "always_flees":
        return target_move_speed
    if policy == "stands_ground":
        return Decimal(0)
    if policy != "range_aware":
        raise ValueError(f"unknown pursuit target policy: {policy}")
    if target_attack_range > actor_attack_range:
        return target_move_speed
    return Decimal(0)


def _stage_noncombat_metrics(
    engine: Any,
    request: Any,
    actor_ids: tuple[int, ...],
    opponent_ids: tuple[int, ...],
    heartsteel_health: Decimal,
    core: int,
    active_duty_policy: str = _DEFAULT_ACTIVE_DUTY_POLICY,
    pursuit_target_policy: str = _DEFAULT_PURSUIT_TARGET_POLICY,
) -> dict[str, Any]:
    """Evaluate pursuit, sustain, chassis, and item readiness for one core.

    :param engine: Matchup engine providing locked item and Cog data.
    :param request: Original matchup request.
    :param actor_ids: Actor build prefix at this core.
    :param opponent_ids: Opponent build prefix at this core.
    :param heartsteel_health: Progression health accumulated before this stage.
    :param core: Current one-based core index.
    :param active_duty_policy: How short, cooldown-bound item actives are credited.
    :param pursuit_target_policy: Whether the pursued opponent retreats.
    :return: Independent non-combat metrics and evidence blockers.
    """
    actor_cog = engine.registry.require_cog(request.actor)
    opponent_cog = engine.registry.require_cog(request.opponent)
    actor_stats = engine._item_stats(actor_ids, request.level, actor_cog, heartsteel_health)
    opponent_stats = engine._item_stats(opponent_ids, request.level, opponent_cog)
    actor = actor_cog.snapshot(level=request.level, item_stats=actor_stats)
    opponent = opponent_cog.snapshot(level=request.level, item_stats=opponent_stats)
    actor_context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        actor,
        opponent,
        request.duration_ms,
        request.horizon_ms,
    )
    opponent_context = ParticipantContext(
        EntityId.TARGET,
        EntityId.ACTOR,
        opponent,
        actor,
        request.duration_ms,
        request.horizon_ms,
    )
    actor_items = tuple(engine._items[item_id] for item_id in actor_ids)
    opponent_items = tuple(engine._items[item_id] for item_id in opponent_ids)
    actor_move = item_engagement_modifiers(
        actor_items,
        actor_context,
        actives_available=True,
        window_ms=_PURSUIT_WINDOW_MS,
        active_duty_policy=active_duty_policy,
    )
    opponent_move = item_engagement_modifiers(
        opponent_items,
        opponent_context,
        actives_available=False,
        window_ms=_PURSUIT_WINDOW_MS,
        active_duty_policy=active_duty_policy,
    )
    engagement = simulate_engagement(
        initial_center_distance=Decimal(650),
        actor_attack_range=actor.attack_range,
        actor_move_speed=actor.move_speed + actor_move.move_speed_flat,
        target_move_speed=_fleeing_move_speed(
            actor.attack_range,
            opponent.attack_range,
            (opponent.move_speed + opponent_move.move_speed_flat)
            * (Decimal(1) + opponent_move.move_speed_percent),
            pursuit_target_policy,
        ),
        window_ms=_PURSUIT_WINDOW_MS,
        actor_speed_multiplier=actor_cog.engagement_speed_multiplier(actor_context)
        * (Decimal(1) + actor_move.move_speed_percent),
        target_slow_fraction=actor_move.target_slow_fraction,
        actor_dash_distance=actor_move.dash_distance
        + actor_cog.engagement_dash_distance(actor_context),
    )
    champion_stats = actor_cog.document["stats"]
    base_regen_per_second = (
        Decimal(str(champion_stats["hpregen"]))
        + Decimal(str(champion_stats["hpregenperlevel"]))
        * actor_cog.growth_multiplier(request.level)
    ) / Decimal(5)
    lane = simulate_lane_sustain(
        max_health=actor.max_hp,
        starting_health_fraction=Decimal("0.5"),
        duration_ms=30_000,
        base_health_regen_per_second=base_regen_per_second,
        base_health_regen_bonus=actor_stats.get("BASE_HEALTH_REGEN_PERCENT", Decimal(0)),
        total_attack_damage=actor.attack_damage,
        lifesteal=actor_stats.get("LIFESTEAL", Decimal(0)),
        minion_attacks=6,
        warmog_ready=warmog_heart_ready(actor.bonus_health),
    )
    champion_lane_extra, champion_lane_blockers = actor_cog.lane_sustain_extra_health(
        actor_context,
        duration_ms=30_000,
        no_damage_delay_ms=8000,
    )
    lane_recovered = min(actor.max_hp * Decimal("0.5"), lane.recovered_health + champion_lane_extra)
    opponent_plan = opponent_cog.build_action_plan(opponent_context)
    raw_by_type = {"PHYSICAL": Decimal(0), "MAGIC": Decimal(0), "TRUE": Decimal(0)}
    for event in opponent_plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR:
                raw_by_type[output.damage_type.value] += output.amount
    raw_total = sum(raw_by_type.values(), Decimal(0))
    if raw_total:
        physical_mix = raw_by_type["PHYSICAL"] / raw_total
        magic_mix = raw_by_type["MAGIC"] / raw_total
        true_mix = raw_by_type["TRUE"] / raw_total
    else:
        physical_mix = magic_mix = Decimal("0.5")
        true_mix = Decimal(0)
    mixed_damage_fraction = (
        physical_mix * Decimal(100) / (Decimal(100) + max(actor.armor, Decimal(0)))
        + magic_mix * Decimal(100) / (Decimal(100) + max(actor.magic_resistance, Decimal(0)))
        + true_mix
    )
    base_actor = actor_cog.snapshot(level=request.level)
    base_damage_fraction = (
        physical_mix * Decimal(100) / (Decimal(100) + max(base_actor.armor, Decimal(0)))
        + magic_mix * Decimal(100) / (Decimal(100) + max(base_actor.magic_resistance, Decimal(0)))
        + true_mix
    )
    mixed_ehp = actor.max_hp / mixed_damage_fraction
    baseline_mixed_ehp = base_actor.max_hp / base_damage_fraction
    chassis_threshold = {1: Decimal("1.15"), 2: Decimal("1.30"), 3: Decimal("1.45")}[core]
    return {
        "uptime": engagement.combat_uptime_fraction,
        "contact": engagement.contact_reached,
        "lane_recovered": lane_recovered,
        "mixed_ehp": mixed_ehp,
        "chassis_ready": mixed_ehp / baseline_mixed_ehp >= chassis_threshold,
        "item_ready": 3083 not in actor_ids or lane.warmog_ready,
        "blockers": (
            *actor_move.blockers,
            *opponent_move.blockers,
            *champion_lane_blockers,
            f"PURSUIT_TARGET_POLICY_ASSUMED:{pursuit_target_policy}",
        ),
    }
