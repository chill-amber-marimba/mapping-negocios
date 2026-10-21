"""Tests for search strategies."""

import pytest

from mapping_negocios.application.strategies import (
    GridProgress,
    GridSearchStrategy,
    ProgressMismatchError,
    TextSearchStrategy,
)
from mapping_negocios.domain.ports import SearchPage

from fakes import REGION, FakeGateway, make_business, make_dense_businesses


def test_text_search_follows_pages_until_no_token(gateway: FakeGateway) -> None:
    """Pagination stops when no next token is returned."""
    gateway.pages = [
        SearchPage([make_business("a")], "t1"),
        SearchPage([make_business("b")], None),
    ]
    result = list(TextSearchStrategy().search(gateway, REGION))
    assert [b.place_id for b in result] == ["a", "b"]
    assert gateway.text_calls == [None, "t1"]


def test_text_search_caps_pages(gateway: FakeGateway) -> None:
    """At most ``max_pages`` requests are made."""
    gateway.pages = [SearchPage([make_business(str(i))], f"t{i}") for i in range(5)]
    assert len(list(TextSearchStrategy(max_pages=3).search(gateway, REGION))) == 3


def test_text_search_filters_outside_region(gateway: FakeGateway) -> None:
    """Results outside the region bounds are dropped."""
    gateway.pages = [SearchPage([make_business("in"), make_business("out", lat=50)])]
    assert [b.place_id for b in TextSearchStrategy().search(gateway, REGION)] == ["in"]


def test_grid_search_one_request_per_unsaturated_tile(gateway: FakeGateway) -> None:
    """Sparse tiles are not subdivided and each business is found once."""
    gateway.nearby = [
        make_business("a", 40.001, -3.799),
        make_business("b", 40.019, -3.781),
    ]
    strategy = GridSearchStrategy(tile_size_m=1000, included_types=["cafe"])
    result = list(strategy.search(gateway, REGION))
    assert sorted(b.place_id for b in result) == ["a", "b"]
    assert strategy.requests_made == 6
    assert all(call[2] == ("cafe",) for call in gateway.nearby_calls)


def test_grid_search_subdivides_saturated_tiles(gateway: FakeGateway) -> None:
    """A tile with 20+ results is split into quadrants to find the rest."""
    gateway.nearby = [
        make_business(
            str(i), 40.0 + 0.0009 * (i % 20 + 1), -3.8 + 0.0008 * (i // 20 + 1)
        )
        for i in range(25)
    ]
    strategy = GridSearchStrategy(tile_size_m=5000, max_depth=3)
    result = {b.place_id for b in strategy.search(gateway, REGION)}
    assert len(result) == 25
    assert strategy.requests_made > 1


def test_grid_search_respects_request_budget(gateway: FakeGateway) -> None:
    """No more than ``max_requests`` calls are made."""
    gateway.nearby = [make_business(str(i), 40.01, -3.79) for i in range(30)]
    strategy = GridSearchStrategy(tile_size_m=500, max_requests=4)
    list(strategy.search(gateway, REGION))
    assert len(gateway.nearby_calls) == 4
    assert strategy.budget_exhausted


def test_grid_search_resumes_from_progress(gateway: FakeGateway) -> None:
    """Budget-limited runs fed back their progress find what one full run finds."""
    gateway.nearby = make_dense_businesses()
    full = GridSearchStrategy(tile_size_m=1000, max_depth=3)
    expected = {b.place_id for b in full.search(gateway, REGION)}
    full_requests = len(gateway.nearby_calls)
    assert not full.budget_exhausted

    gateway.nearby_calls.clear()
    found: set[str] = set()
    progress: GridProgress | None = None
    runs = 0
    while True:
        runs += 1
        strategy = GridSearchStrategy(
            tile_size_m=1000, max_depth=3, max_requests=3, progress=progress
        )
        found |= {b.place_id for b in strategy.search(gateway, REGION)}
        progress = strategy.progress
        if not strategy.budget_exhausted:
            break

    assert found == expected
    assert runs > 1
    # No box is searched twice across runs.
    assert len(gateway.nearby_calls) == full_requests


def test_grid_search_rejects_progress_of_another_search(
    gateway: FakeGateway,
) -> None:
    """Progress saved with other place types cannot be reused."""
    progress = GridProgress(REGION.bounds, 1000, ("cafe",))
    strategy = GridSearchStrategy(
        tile_size_m=1000, included_types=["bar"], progress=progress
    )
    with pytest.raises(ProgressMismatchError):
        list(strategy.search(gateway, REGION))
    assert gateway.nearby_calls == []
