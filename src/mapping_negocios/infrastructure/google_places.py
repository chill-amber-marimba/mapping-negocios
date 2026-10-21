"""Google Places API (New) adapter implementing ``PlacesGateway``.

Docs: https://developers.google.com/maps/documentation/places/web-service/op-overview
The field masks below determine the billed SKU: removing fields can lower cost.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from mapping_negocios.domain.models import (
    BoundingBox,
    Business,
    Coordinates,
    PlacesApiError,
    Region,
    RegionNotFoundError,
)
from mapping_negocios.domain.ports import SearchPage

logger = logging.getLogger(__name__)

BASE_URL = "https://places.googleapis.com/v1"
MAX_PAGE_SIZE = 20
MAX_NEARBY_RADIUS_M = 50_000.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

PLACE_FIELDS = (
    "id",
    "displayName",
    "primaryType",
    "types",
    "location",
    "formattedAddress",
    "addressComponents",
    "internationalPhoneNumber",
    "websiteUri",
    "rating",
    "userRatingCount",
    "businessStatus",
    "googleMapsUri",
)
PLACES_FIELD_MASK = ",".join(f"places.{f}" for f in PLACE_FIELDS)
TEXT_SEARCH_FIELD_MASK = f"{PLACES_FIELD_MASK},nextPageToken"
GEOCODE_FIELD_MASK = "places.displayName,places.formattedAddress,places.viewport"

# TODO(me): Substitute the Json definition by the one defined by the preferred
# library (probably orjson).
Json = dict[str, Any]


class GooglePlacesClient:
    """HTTP client for the Places API (New)."""

    def __init__(
        self,
        api_key: str,
        http_client: httpx.Client | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the client.

        Args:
            api_key: Google Maps Platform API key with Places API (New) enabled.
            http_client: Optional preconfigured client (useful for tests).
            max_retries: Retries for rate limiting and transient server errors.
            sleep: Sleep function used for backoff (injectable for tests).
        """
        self._http = http_client or httpx.Client(base_url=BASE_URL, timeout=30.0)
        self._api_key = api_key
        self._max_retries = max_retries
        self._sleep = sleep

    def geocode(self, name: str) -> Region:
        """Resolve a place name to its viewport.

        Args:
            name: Place name, e.g. ``"Chamberí, Madrid"``.

        Returns:
            The resolved region.

        Raises:
            RegionNotFoundError: If no place or viewport matches ``name``.
        """
        data = self._post(
            "/places:searchText", {"textQuery": name, "pageSize": 1}, GEOCODE_FIELD_MASK
        )
        places = data.get("places") or []
        if not places or "viewport" not in places[0]:
            raise RegionNotFoundError(f"Could not resolve region: {name!r}")
        place = places[0]
        viewport = place["viewport"]
        bounds = BoundingBox(
            south=viewport["low"]["latitude"],
            west=viewport["low"]["longitude"],
            north=viewport["high"]["latitude"],
            east=viewport["high"]["longitude"],
        )
        return Region(name=place.get("formattedAddress") or name, bounds=bounds)

    def search_text(
        self, query: str, bounds: BoundingBox, page_token: str | None = None
    ) -> SearchPage:
        """Run one page of Text Search restricted to ``bounds``.

        Args:
            query: Free text query.
            bounds: Rectangle results must fall in.
            page_token: Token from a previous page, if any.

        Returns:
            Businesses in the page and the next page token.
        """
        body: Json = {
            "textQuery": query,
            "pageSize": MAX_PAGE_SIZE,
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": bounds.south, "longitude": bounds.west},
                    "high": {"latitude": bounds.north, "longitude": bounds.east},
                }
            },
        }
        if page_token:
            body["pageToken"] = page_token
        data = self._post("/places:searchText", body, TEXT_SEARCH_FIELD_MASK)
        return SearchPage(
            businesses=[_to_business(p) for p in data.get("places", [])],
            next_page_token=data.get("nextPageToken"),
        )

    def search_nearby(
        self, center: Coordinates, radius_m: float, included_types: Sequence[str] = ()
    ) -> list[Business]:
        """Run a Nearby Search within a circle.

        Args:
            center: Circle center.
            radius_m: Circle radius in meters (capped at the API maximum).
            included_types: Place types to filter by; empty means all types.

        Returns:
            Up to 20 businesses.
        """
        body: Json = {
            "maxResultCount": MAX_PAGE_SIZE,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": center.latitude,
                        "longitude": center.longitude,
                    },
                    "radius": min(radius_m, MAX_NEARBY_RADIUS_M),
                }
            },
        }
        if included_types:
            body["includedTypes"] = list(included_types)
        data = self._post("/places:searchNearby", body, PLACES_FIELD_MASK)
        return [_to_business(p) for p in data.get("places", [])]

    def _post(self, path: str, body: Json, field_mask: str) -> Json:
        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": field_mask}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(path, json=body, headers=headers)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise PlacesApiError(
                        f"Network error calling {path}: {exc}"
                    ) from exc
            else:
                if (
                    response.status_code not in RETRYABLE_STATUS
                    or attempt == self._max_retries
                ):
                    break
            delay = 2**attempt
            logger.info("Retrying %s in %ss (attempt %d)", path, delay, attempt + 1)
            self._sleep(delay)
        if response.is_error:
            raise PlacesApiError(
                f"{path} failed with {response.status_code}: {response.text}"
            )
        return response.json()


def _component(components: list[Json], component_type: str) -> str | None:
    return next(
        (c.get("longText") for c in components if component_type in c.get("types", [])),
        None,
    )


def _to_business(place: Json) -> Business:
    components = place.get("addressComponents", [])
    location = place.get("location", {})
    return Business(
        place_id=place["id"],
        name=place.get("displayName", {}).get("text", ""),
        location=Coordinates(
            location.get("latitude", 0.0), location.get("longitude", 0.0)
        ),
        primary_type=place.get("primaryType"),
        types=tuple(place.get("types", [])),
        formatted_address=place.get("formattedAddress"),
        postal_code=_component(components, "postal_code"),
        locality=_component(components, "locality"),
        admin_region=_component(components, "administrative_area_level_1"),
        country=_component(components, "country"),
        phone=place.get("internationalPhoneNumber"),
        website=place.get("websiteUri"),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        business_status=place.get("businessStatus"),
        google_maps_uri=place.get("googleMapsUri"),
    )
