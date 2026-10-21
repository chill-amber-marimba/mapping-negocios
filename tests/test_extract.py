"""Tests for the extraction use case and DataFrame conversion."""

from mapping_negocios.application.extract import ExtractBusinesses
from mapping_negocios.application.frames import (
    BUSINESS_SCHEMA,
    businesses_to_frame,
    summarize_by_type,
)
from mapping_negocios.application.strategies import TextSearchStrategy
from mapping_negocios.domain.ports import SearchPage

from fakes import FakeGateway, make_business


def test_extract_deduplicates_by_place_id(gateway: FakeGateway) -> None:
    """Duplicate place ids across pages appear once."""
    gateway.pages = [
        SearchPage([make_business("a"), make_business("b")], "t"),
        SearchPage([make_business("a")], None),
    ]
    result = ExtractBusinesses(gateway, TextSearchStrategy())("Test Town")
    assert result.businesses["place_id"].to_list() == ["a", "b"]
    assert result.businesses["search_region"].unique().to_list() == ["Test Town"]
    assert result.businesses.schema == BUSINESS_SCHEMA


def test_empty_frame_keeps_schema() -> None:
    """No businesses still yields a typed, empty DataFrame."""
    frame = businesses_to_frame([], "Nowhere")
    assert frame.is_empty()
    assert frame.schema == BUSINESS_SCHEMA


def test_summarize_by_type() -> None:
    """Counts are sorted descending."""
    frame = businesses_to_frame(
        [
            make_business("a", primary_type="cafe"),
            make_business("b", primary_type="cafe"),
            make_business("c", primary_type="bank"),
        ],
        "X",
    )
    summary = summarize_by_type(frame)
    assert summary.rows() == [("cafe", 2), ("bank", 1)]
