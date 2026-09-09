"""Worker count must change search speed without changing its result."""

from pathlib import Path

from lol_build.application.cog_preview import (
    _prefill_stage_cache,
    _stage_pool,
    generic_cog_build_preview,
)
from lol_build.application.matchup import MatchupEngine, MatchupRequest

ROOT = Path(__file__).resolve().parents[1]


def branches(preview: object) -> dict[str, tuple[int, ...]]:
    """Reduce a preview to its selected builds.

    :param preview: Completed build preview.
    :return: Item path per branch name.
    """
    return {
        branch.value: tuple(selected.item_ids)
        for branch, selected in preview.branches.items()  # type: ignore[attr-defined]
    }


def test_a_single_worker_keeps_the_search_in_this_process() -> None:
    """Yield no pool for a sequential run so nothing is spawned."""
    with _stage_pool(1, ROOT, None, None) as pool:
        assert pool is None


def test_prefill_without_a_pool_leaves_the_cache_untouched() -> None:
    """Skip prefilling when running inline; the sequential pass fills the cache."""
    cache: dict[tuple[tuple[int, ...], int, int], object] = {}
    _prefill_stage_cache([], 1, cache, pool=None, workers=1)  # type: ignore[arg-type]

    assert cache == {}


def test_parallel_and_sequential_searches_agree_exactly() -> None:
    """Produce identical builds and metrics regardless of worker count."""
    engine = MatchupEngine(ROOT)

    def preview(workers: int) -> object:
        """Run one bounded search at a given worker count.

        :param workers: Worker processes to use.
        :return: Completed preview.
        """
        return generic_cog_build_preview(
            engine,
            MatchupRequest("Darius", "Aatrox", opponent_item_ids=(3071, 3053, 6333)),
            workers=workers,
        )

    sequential = preview(1)
    parallel = preview(4)

    assert branches(parallel) == branches(sequential)
    assert parallel.evaluated_candidate_count == sequential.evaluated_candidate_count
    for branch, selected in sequential.branches.items():
        assert parallel.branches[branch].metrics == selected.metrics
