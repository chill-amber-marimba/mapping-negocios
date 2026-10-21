"""Core entities and value objects of the domain."""

import math
from dataclasses import dataclass, field
from enum import StrEnum

EARTH_RADIUS_M = 6_371_000.0


class Adherencia(StrEnum):
    """Semaphore of how likely a business is to adhere (e.g. join the strike)."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class PlacesApiError(Exception):
    """Raised when the places provider fails or returns an unexpected response."""


class RegionNotFoundError(Exception):
    """Raised when a region name cannot be resolved to a geographic area."""


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A WGS84 point."""

    latitude: float
    longitude: float

    def distance_m(self, other: "Coordinates") -> float:
        """Great-circle distance to another point using the haversine formula.

        Args:
            other: The other point.

        Returns:
            Distance in meters.
        """
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        dlat = lat2 - lat1
        dlng = math.radians(other.longitude - self.longitude)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        )
        return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned lat/lng rectangle (does not support antimeridian crossing)."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        """Validate that the box is not inverted."""
        if self.south > self.north or self.west > self.east:
            raise ValueError(f"Invalid bounding box: {self}")

    @property
    def center(self) -> Coordinates:
        """Geometric center of the box."""
        return Coordinates((self.south + self.north) / 2, (self.west + self.east) / 2)

    @property
    def circumscribed_radius_m(self) -> float:
        """Radius of the smallest circle centered in the box that contains it."""
        return self.center.distance_m(Coordinates(self.north, self.east))

    def contains(self, point: Coordinates) -> bool:
        """Check whether a point lies inside the box (edges included).

        Args:
            point: The point to test.

        Returns:
            True if the point is inside the box.
        """
        return (
            self.south <= point.latitude <= self.north
            and self.west <= point.longitude <= self.east
        )

    def quadrants(
        self,
    ) -> tuple["BoundingBox", "BoundingBox", "BoundingBox", "BoundingBox"]:
        """Split the box into four equal quadrants (SW, SE, NW, NE)."""
        mid = self.center
        return (
            BoundingBox(self.south, self.west, mid.latitude, mid.longitude),
            BoundingBox(self.south, mid.longitude, mid.latitude, self.east),
            BoundingBox(mid.latitude, self.west, self.north, mid.longitude),
            BoundingBox(mid.latitude, mid.longitude, self.north, self.east),
        )

    def split_into_tiles(self, tile_size_m: float) -> list["BoundingBox"]:
        """Split the box into a grid of tiles of roughly ``tile_size_m`` per side.

        Args:
            tile_size_m: Desired tile side length in meters.

        Returns:
            Tiles covering the whole box, row by row from south-west.
        """
        if tile_size_m <= 0:
            raise ValueError("tile_size_m must be positive")
        height_m = Coordinates(self.south, self.west).distance_m(
            Coordinates(self.north, self.west)
        )
        mid_lat = self.center.latitude
        width_m = Coordinates(mid_lat, self.west).distance_m(
            Coordinates(mid_lat, self.east)
        )
        rows = max(1, math.ceil(height_m / tile_size_m))
        cols = max(1, math.ceil(width_m / tile_size_m))
        dlat = (self.north - self.south) / rows
        dlng = (self.east - self.west) / cols
        return [
            BoundingBox(
                self.south + r * dlat,
                self.west + c * dlng,
                self.south + (r + 1) * dlat,
                self.west + (c + 1) * dlng,
            )
            for r in range(rows)
            for c in range(cols)
        ]


@dataclass(frozen=True, slots=True)
class Region:
    """A named geographic area to search in."""

    name: str
    bounds: BoundingBox


@dataclass(frozen=True, slots=True)
class Business:
    """A business (place) found in a region."""

    place_id: str
    name: str
    location: Coordinates
    primary_type: str | None = None
    types: tuple[str, ...] = field(default_factory=tuple)
    formatted_address: str | None = None
    postal_code: str | None = None
    locality: str | None = None
    admin_region: str | None = None
    country: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    business_status: str | None = None
    google_maps_uri: str | None = None
    adherencia: Adherencia | None = None  # None until assessed
