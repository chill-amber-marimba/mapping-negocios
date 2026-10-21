"""Ports (interfaces) the domain needs from the outside world."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from mapping_negocios.domain.models import BoundingBox, Business, Coordinates, Region


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of search results plus the token to fetch the next one."""

    businesses: list[Business]
    next_page_token: str | None = None


class PlacesGateway(Protocol):
    """Source of geographic and business data (e.g. Google Places)."""

    def geocode(self, name: str) -> Region:
        """Resolve a place name to a region with bounds."""
        ...

    def search_text(
        self, query: str, bounds: BoundingBox, page_token: str | None = None
    ) -> SearchPage:
        """Free-text search restricted to ``bounds``."""
        ...

    def search_nearby(
        self, center: Coordinates, radius_m: float, included_types: Sequence[str] = ()
    ) -> list[Business]:
        """Search places within a circle, optionally filtered by place types."""
        ...
