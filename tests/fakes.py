"""Test doubles and builders shared across the test suite.

Importable as ``fakes`` because ``tests`` is on pytest's ``pythonpath``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from mapping_negocios.domain.models import (
    Adherencia,
    BoundingBox,
    Business,
    Coordinates,
    Region,
)
from mapping_negocios.domain.ports import SearchPage

REGION = Region(
    "Test Town", BoundingBox(south=40.0, west=-3.8, north=40.02, east=-3.78)
)


def make_business(
    place_id: str,
    lat: float = 40.01,
    lng: float = -3.79,
    *,
    primary_type: str | None = None,
    types: tuple[str, ...] = (),
    phone: str | None = None,
    postal_code: str | None = None,
    adherencia: Adherencia | None = None,
) -> Business:
    """Build a business with sensible defaults."""
    return Business(
        place_id=place_id,
        name=f"Biz {place_id}",
        location=Coordinates(lat, lng),
        primary_type=primary_type,
        types=types,
        phone=phone,
        postal_code=postal_code,
        adherencia=adherencia,
    )


@dataclass
class FakeGateway:
    """In-memory ``PlacesGateway``."""

    region: Region = REGION
    pages: list[SearchPage] = field(default_factory=list)
    nearby: list[Business] = field(default_factory=list)
    text_calls: list[str | None] = field(default_factory=list)
    nearby_calls: list[tuple[Coordinates, float, tuple[str, ...]]] = field(
        default_factory=list
    )

    def geocode(self, name: str) -> Region:
        """Return the configured region."""
        return self.region

    def search_text(
        self, query: str, bounds: BoundingBox, page_token: str | None = None
    ) -> SearchPage:
        """Return pages in order, ignoring the token value."""
        self.text_calls.append(page_token)
        return self.pages[len(self.text_calls) - 1]

    def search_nearby(
        self, center: Coordinates, radius_m: float, included_types: Sequence[str] = ()
    ) -> list[Business]:
        """Return configured businesses within the circle, max 20."""
        self.nearby_calls.append((center, radius_m, tuple(included_types)))
        hits = [b for b in self.nearby if center.distance_m(b.location) <= radius_m]
        return hits[:20]
