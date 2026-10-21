"""Strategies to collect businesses within a region."""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
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


@dataclass(slots=True)
class GridSearchStrategy:
    """Thorough search: Nearby Search over a grid, subdividing saturated tiles.

    Each tile is queried with its circumscribed circle; results outside the tile
    are discarded so neighbouring tiles don't double count. A tile returning a
    full page is split into quadrants until ``max_depth``. ``max_requests``
    caps API cost.
    """

    tile_size_m: float = 1000.0
    included_types: Sequence[str] = ()
    max_depth: int = 3
    max_requests: int = 200
    requests_made: int = 0

    def search(self, gateway: PlacesGateway, region: Region) -> Iterator[Business]:
        """Yield businesses found tile by tile.

        Args:
            gateway: Places data source.
            region: Region to search in.

        Yields:
            Businesses inside the region bounds.
        """
        self.requests_made = 0
        for tile in region.bounds.split_into_tiles(self.tile_size_m):
            yield from self._search_tile(gateway, tile, depth=0)

    def _search_tile(
        self, gateway: PlacesGateway, tile: BoundingBox, depth: int
    ) -> Iterator[Business]:
        if self.requests_made >= self.max_requests:
            logger.warning(
                "Request budget (%d) exhausted; results are partial.", self.max_requests
            )
            return
        self.requests_made += 1
        results = gateway.search_nearby(
            tile.center, tile.circumscribed_radius_m, self.included_types
        )
        if len(results) >= NEARBY_SEARCH_MAX_RESULTS and depth < self.max_depth:
            for quadrant in tile.quadrants():
                yield from self._search_tile(gateway, quadrant, depth + 1)
            return
        if len(results) >= NEARBY_SEARCH_MAX_RESULTS:
            logger.warning(
                "Tile %s still saturated at max depth; results may be partial.", tile
            )
        yield from (b for b in results if tile.contains(b.location))
