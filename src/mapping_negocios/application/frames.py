"""Conversion between domain entities and Polars DataFrames, plus the I/O ports."""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import polars as pl

from mapping_negocios.domain.models import Adherencia, Business

# TODO(me): define this from a common constant, if possible (https://docs.pola.rs/api/python/stable/reference/schema/index.html)
BUSINESS_SCHEMA = pl.Schema(
    {
        "place_id": pl.String,
        "name": pl.String,
        "primary_type": pl.String,
        "types": pl.List(pl.String),
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "formatted_address": pl.String,
        "postal_code": pl.String,
        "locality": pl.String,
        "admin_region": pl.String,
        "country": pl.String,
        "phone": pl.String,
        "website": pl.String,
        "rating": pl.Float64,
        "user_rating_count": pl.Int64,
        "business_status": pl.String,
        "google_maps_uri": pl.String,
        "search_region": pl.String,
        "adherencia": pl.Enum(Adherencia),
    }
)
# Joins list columns (e.g. ``types``) in text formats such as CSV and KML.
LIST_SEPARATOR = "|"
# ``BUSINESS_SCHEMA`` with list columns as joined text, for formats with no lists.
FLAT_BUSINESS_SCHEMA = pl.Schema(
    {
        name: pl.String if isinstance(dtype, pl.List) else dtype
        for name, dtype in BUSINESS_SCHEMA.items()
    }
)


class BusinessExporter(Protocol):
    """Writes a businesses DataFrame to some destination."""

    extension: str

    def export(self, frame: pl.DataFrame, path: Path, title: str) -> Path:
        """Write ``frame`` to ``path`` and return the written path."""
        ...


class BusinessImporter(Protocol):
    """Reads a businesses DataFrame back from some source."""

    extension: str

    def read(self, path: Path) -> pl.DataFrame:
        """Read ``path`` into a DataFrame with ``BUSINESS_SCHEMA``."""
        ...


def unflatten(frame: pl.DataFrame) -> pl.DataFrame:
    """Turn a ``FLAT_BUSINESS_SCHEMA`` DataFrame into a ``BUSINESS_SCHEMA`` one.

    Args:
        frame: DataFrame with list columns joined by ``LIST_SEPARATOR``.

    Returns:
        A DataFrame with ``BUSINESS_SCHEMA``; empty or null lists become ``[]``.
    """
    return frame.with_columns(
        pl.col(name)
        .str.split(LIST_SEPARATOR)
        .list.filter(pl.element() != "")
        .fill_null(pl.lit([], dtype))
        for name, dtype in BUSINESS_SCHEMA.items()
        if isinstance(dtype, pl.List)
    )


def businesses_to_frame(
    businesses: Iterable[Business], search_region: str
) -> pl.DataFrame:
    """Build a DataFrame with ``BUSINESS_SCHEMA`` from business entities.

    Args:
        businesses: Entities to convert.
        search_region: Name of the region the search was made for.

    Returns:
        A DataFrame with one row per business (empty but typed if no input).
    """
    rows = [
        {
            "place_id": b.place_id,
            "name": b.name,
            "primary_type": b.primary_type,
            "types": list(b.types),
            "latitude": b.location.latitude,
            "longitude": b.location.longitude,
            "formatted_address": b.formatted_address,
            "postal_code": b.postal_code,
            "locality": b.locality,
            "admin_region": b.admin_region,
            "country": b.country,
            "phone": b.phone,
            "website": b.website,
            "rating": b.rating,
            "user_rating_count": b.user_rating_count,
            "business_status": b.business_status,
            "google_maps_uri": b.google_maps_uri,
            "search_region": search_region,
            "adherencia": b.adherencia,
        }
        for b in businesses
    ]
    return pl.DataFrame(rows, schema=BUSINESS_SCHEMA)


def merge_businesses(previous: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """Append ``new`` businesses to ``previous`` ones, one row per place.

    Args:
        previous: Businesses already extracted (they win on duplicates, so edits
            such as a filled ``adherencia`` are kept).
        new: Businesses from a follow-up extraction.

    Returns:
        A DataFrame with ``BUSINESS_SCHEMA``.
    """
    return pl.concat([previous, new]).unique(
        "place_id", keep="first", maintain_order=True
    )


def summarize_by_type(frame: pl.DataFrame) -> pl.DataFrame:
    """Count businesses per primary type, most common first.

    Args:
        frame: DataFrame with ``BUSINESS_SCHEMA``.

    Returns:
        DataFrame with ``primary_type`` and ``count`` columns.
    """
    return (
        frame.group_by("primary_type")
        .len(name="count")
        .sort(["count", "primary_type"], descending=[True, False], nulls_last=True)
    )
