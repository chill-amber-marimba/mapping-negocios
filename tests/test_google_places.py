"""Tests for the Google Places adapter using a mocked HTTP transport."""

import json

import httpx
import pytest

from mapping_negocios.domain.models import (
    BoundingBox,
    Coordinates,
    PlacesApiError,
    RegionNotFoundError,
)
from mapping_negocios.infrastructure.google_places import (
    BASE_URL,
    MAX_NEARBY_RADIUS_M,
    GooglePlacesClient,
)

PLACE = {
    "id": "abc",
    "displayName": {"text": "Café Pepe", "languageCode": "es"},
    "primaryType": "cafe",
    "types": ["cafe", "food", "establishment"],
    "location": {"latitude": 40.43, "longitude": -3.70},
    "formattedAddress": "Calle Falsa 1, 28010 Madrid, Spain",
    "addressComponents": [
        {"longText": "28010", "shortText": "28010", "types": ["postal_code"]},
        {
            "longText": "Madrid",
            "shortText": "Madrid",
            "types": ["locality", "political"],
        },
        {"longText": "Comunidad de Madrid", "types": ["administrative_area_level_1"]},
        {"longText": "Spain", "shortText": "ES", "types": ["country", "political"]},
    ],
    "internationalPhoneNumber": "+34 600 000 000",
    "websiteUri": "https://pepe.example",
    "rating": 4.5,
    "userRatingCount": 120,
    "businessStatus": "OPERATIONAL",
    "googleMapsUri": "https://maps.google.com/?cid=1",
}
BOX = BoundingBox(40.42, -3.71, 40.44, -3.69)


def make_client(
    handler: httpx.MockTransport | None = None,
    responses: list[httpx.Response] | None = None,
) -> tuple[GooglePlacesClient, list[httpx.Request]]:
    """Client whose HTTP calls are captured and answered from ``responses``."""
    requests: list[httpx.Request] = []
    queue = list(responses or [])

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    transport = handler or httpx.MockTransport(respond)
    http = httpx.Client(base_url=BASE_URL, transport=transport)
    return GooglePlacesClient("KEY", http_client=http, sleep=lambda _: None), requests


def test_search_text_maps_place_and_sends_headers() -> None:
    """Response fields map to a Business; key and field mask are sent."""
    client, requests = make_client(
        responses=[
            httpx.Response(200, json={"places": [PLACE], "nextPageToken": "next"})
        ]
    )
    page = client.search_text("cafés", BOX, page_token="tok")

    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/places:searchText"
    assert request.headers["X-Goog-Api-Key"] == "KEY"
    assert "places.addressComponents" in request.headers["X-Goog-FieldMask"]
    assert "nextPageToken" in request.headers["X-Goog-FieldMask"]
    assert body["pageToken"] == "tok"
    assert body["locationRestriction"]["rectangle"]["low"] == {
        "latitude": 40.42,
        "longitude": -3.71,
    }

    assert page.next_page_token == "next"
    business = page.businesses[0]
    assert business.name == "Café Pepe"
    assert business.location == Coordinates(40.43, -3.70)
    assert business.postal_code == "28010"
    assert business.locality == "Madrid"
    assert business.admin_region == "Comunidad de Madrid"
    assert business.country == "Spain"
    assert business.types == ("cafe", "food", "establishment")
    assert business.user_rating_count == 120


def test_search_nearby_caps_radius_and_sends_types() -> None:
    """Radius is capped at the API max and types are forwarded."""
    client, requests = make_client(responses=[httpx.Response(200, json={})])
    assert client.search_nearby(Coordinates(40, -3), 99_999, ["cafe"]) == []
    body = json.loads(requests[0].content)
    assert body["locationRestriction"]["circle"]["radius"] == MAX_NEARBY_RADIUS_M
    assert body["includedTypes"] == ["cafe"]


def test_geocode_uses_viewport() -> None:
    """The first match's viewport becomes the region bounds."""
    viewport = {
        "low": {"latitude": 1, "longitude": 2},
        "high": {"latitude": 3, "longitude": 4},
    }
    client, _ = make_client(
        responses=[
            httpx.Response(
                200,
                json={
                    "places": [{"formattedAddress": "Somewhere", "viewport": viewport}]
                },
            )
        ]
    )
    region = client.geocode("somewhere")
    assert region.name == "Somewhere"
    assert region.bounds == BoundingBox(1, 2, 3, 4)


def test_geocode_not_found() -> None:
    """Empty results raise RegionNotFoundError."""
    client, _ = make_client(responses=[httpx.Response(200, json={})])
    with pytest.raises(RegionNotFoundError):
        client.geocode("nowhere")


def test_retries_transient_errors_then_succeeds() -> None:
    """429/5xx are retried."""
    client, requests = make_client(
        responses=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json={}),
        ]
    )
    assert client.search_nearby(Coordinates(40, -3), 100) == []
    assert len(requests) == 3


def test_client_error_raises_places_api_error() -> None:
    """Non-retryable errors raise immediately."""
    client, requests = make_client(responses=[httpx.Response(403, text="denied")])
    with pytest.raises(PlacesApiError, match="403"):
        client.search_nearby(Coordinates(40, -3), 100)
    assert len(requests) == 1


def test_network_error_raises_after_retries() -> None:
    """Transport errors are retried, then wrapped."""

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client, _ = make_client(handler=httpx.MockTransport(fail))
    with pytest.raises(PlacesApiError, match="Network error"):
        client.search_nearby(Coordinates(40, -3), 100)
