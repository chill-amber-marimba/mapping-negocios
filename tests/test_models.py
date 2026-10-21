"""Tests for domain value objects."""

import pytest

from mapping_negocios.domain.models import BoundingBox, Coordinates

BOX = BoundingBox(south=40.0, west=-3.8, north=40.02, east=-3.78)


def test_distance_one_degree_latitude() -> None:
    """One degree of latitude is ~111 km."""
    assert Coordinates(0, 0).distance_m(Coordinates(1, 0)) == pytest.approx(
        111_195, rel=1e-3
    )


def test_invalid_box_raises() -> None:
    """Inverted boxes are rejected."""
    with pytest.raises(ValueError, match="Invalid"):
        BoundingBox(south=1, west=0, north=0, east=1)


def test_contains_and_center() -> None:
    """Center is inside, outside points are not."""
    assert BOX.contains(BOX.center)
    assert not BOX.contains(Coordinates(41, -3.79))


def test_quadrants_cover_box() -> None:
    """Quadrants tile the original box exactly."""
    sw, se, nw, ne = BOX.quadrants()
    assert (sw.south, sw.west, ne.north, ne.east) == (
        BOX.south,
        BOX.west,
        BOX.north,
        BOX.east,
    )
    assert sw.north == nw.south and sw.east == se.west


def test_split_into_tiles_covers_box() -> None:
    """Tiles cover the box with roughly the requested size."""
    tiles = BOX.split_into_tiles(1000)
    # Box is ~2.2 km tall and ~1.7 km wide -> 3 x 2 tiles.
    assert len(tiles) == 6
    assert min(t.south for t in tiles) == BOX.south
    assert max(t.north for t in tiles) == pytest.approx(BOX.north)
    assert max(t.east for t in tiles) == pytest.approx(BOX.east)
    assert all(t.circumscribed_radius_m < 1000 for t in tiles)


def test_split_into_tiles_rejects_non_positive() -> None:
    """Tile size must be positive."""
    with pytest.raises(ValueError, match="positive"):
        BOX.split_into_tiles(0)
