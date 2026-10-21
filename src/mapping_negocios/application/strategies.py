"""Strategies to collect businesses within a region."""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from mapping_negocios.domain.models import BoundingBox, Business, Region
from mapping_negocios.domain.ports import PlacesGateway

logger = logging.getLogger(__name__)

TEXT_SEARCH_MAX_PAGES = 3  # Google caps Text Search at 60 results (3 x 20).
NEARBY_SEARCH_MAX_RESULTS = 20  # A full page means there may be more results.


class SearchStrategy(Protocol):
    """Collects businesses for a region using a ``PlacesGateway``."""

    def search(self, gateway: PlacesGateway, region: Region) -> Iterator[Business]:
        """Yield businesses found in ``region`` (may contain duplicates)."""
        ...


@dataclass(frozen=True, slots=True)
class TextSearchStrategy:
    """Cheap search: one paginated Text Search over the region (max 60 results)."""

    query: str = "businesses"
    max_pages: int = TEXT_SEARCH_MAX_PAGES

    def search(self, gateway: PlacesGateway, region: Region) -> Iterator[Business]:
        """Yield up to ``max_pages`` pages of Text Search results.

        Args:
            gateway: Places data source.
            region: Region to search in.

        Yields:
            Businesses inside the region bounds.
        """
        token: str | None = None
        for _ in range(self.max_pages):
            page = gateway.search_text(self.query, region.bounds, token)
            yield from (
                b for b in page.businesses if region.bounds.contains(b.location)
            )
            token = page.next_page_token
            if not token:
                return


class ProgressMismatchError(Exception):
    """Raised when saved grid progress belongs to a different search."""


@dataclass(slots=True)
class GridProgress:
    """Boxes a grid search already covered, so a follow-up run can skip them.

    Boxes only match across runs of the same search, identified by the region
    bounds, tile size and place types.
    """

    region_bounds: BoundingBox
    tile_size_m: float
    included_types: tuple[str, ...] = ()
    # Searched boxes whose results were kept.
    completed: set[BoundingBox] = field(default_factory=set)
    # Searched boxes that returned a full page and were split into quadrants.
    saturated: set[BoundingBox] = field(default_factory=set)

    def matches(
        self, bounds: BoundingBox, tile_size_m: float, included_types: Sequence[str]
    ) -> bool:
        """Check whether this progress belongs to the given search.

        Args:
            bounds: Region bounds of the search.
            tile_size_m: Grid tile size of the search.
            included_types: Place types of the search.

        Returns:
            True if the saved boxes can be reused for that search.
        """
        return (
            self.region_bounds == bounds
            and self.tile_size_m == tile_size_m
            and self.included_types == tuple(included_types)
        )


@dataclass(slots=True)
class GridSearchStrategy:
    """Thorough search: Nearby Search over a grid, subdividing saturated tiles.

    Each tile is queried with its circumscribed circle; results outside the tile
    are discarded so neighbouring tiles don't double count. A tile returning a
    full page is split into quadrants until ``max_depth``. ``max_requests``
    caps API cost; ``progress`` records the boxes covered so a follow-up run,
    given that progress back, resumes where the budget ran out.
    ``box_results`` holds the businesses kept from each box searched in the
    last run.
    """

    tile_size_m: float = 1000.0
    included_types: Sequence[str] = ()
    max_depth: int = 3
    max_requests: int = 200
    progress: GridProgress | None = None
    requests_made: int = 0
    budget_exhausted: bool = False
    box_results: dict[BoundingBox, list[Business]] = field(default_factory=dict)

    def search(self, gateway: PlacesGateway, region: Region) -> Iterator[Business]:
        """Yield businesses found tile by tile, skipping boxes in ``progress``.

        Args:
            gateway: Places data source.
            region: Region to search in.

        Yields:
            Businesses inside the region bounds.

        Raises:
            ProgressMismatchError: If ``progress`` belongs to another search.
        """
        if self.progress is None:
            self.progress = GridProgress(
                region.bounds, self.tile_size_m, tuple(self.included_types)
            )
        elif not self.progress.matches(
            region.bounds, self.tile_size_m, self.included_types
        ):
            raise ProgressMismatchError(
                "Saved progress is for another region, tile size or place types."
            )
        self.requests_made = 0
        self.budget_exhausted = False
        self.box_results = {}
        for tile in region.bounds.split_into_tiles(self.tile_size_m):
            yield from self._search_tile(gateway, self.progress, tile, depth=0)

    def _search_tile(
        self,
        gateway: PlacesGateway,
        progress: GridProgress,
        tile: BoundingBox,
        depth: int,
    ) -> Iterator[Business]:
        if tile in progress.completed:
            return
        if tile in progress.saturated and depth < self.max_depth:
            for quadrant in tile.quadrants():
                yield from self._search_tile(gateway, progress, quadrant, depth + 1)
            return
        if self.requests_made >= self.max_requests:
            if not self.budget_exhausted:
                logger.warning(
                    "Request budget (%d) exhausted; results are partial.",
                    self.max_requests,
                )
            self.budget_exhausted = True
            return
        self.requests_made += 1
        results = gateway.search_nearby(
            tile.center, tile.circumscribed_radius_m, self.included_types
        )
        if len(results) >= NEARBY_SEARCH_MAX_RESULTS and depth < self.max_depth:
            progress.saturated.add(tile)
            for quadrant in tile.quadrants():
                yield from self._search_tile(gateway, progress, quadrant, depth + 1)
            return
        if len(results) >= NEARBY_SEARCH_MAX_RESULTS:
            logger.warning(
                "Tile %s still saturated at max depth; results may be partial.", tile
            )
        found = [b for b in results if tile.contains(b.location)]
        progress.completed.add(tile)
        self.box_results[tile] = found
        yield from found
