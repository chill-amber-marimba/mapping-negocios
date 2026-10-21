"""Use case: extract all businesses of a named region into a DataFrame."""

from dataclasses import dataclass

import polars as pl

from mapping_negocios.application.frames import businesses_to_frame
from mapping_negocios.application.strategies import SearchStrategy
from mapping_negocios.domain.models import Business, Region
from mapping_negocios.domain.ports import PlacesGateway


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Output of ``ExtractBusinesses``."""

    region: Region
    businesses: pl.DataFrame


@dataclass(frozen=True, slots=True)
class ExtractBusinesses:
    """Resolve a region name and collect its businesses with a search strategy."""

    gateway: PlacesGateway
    strategy: SearchStrategy

    def __call__(self, region_name: str) -> ExtractionResult:
        """Run the extraction.

        Args:
            region_name: Human readable place name, e.g. ``"Chamberí, Madrid"``.

        Returns:
            The resolved region and a deduplicated DataFrame of businesses.
        """
        region = self.gateway.geocode(region_name)
        unique: dict[str, Business] = {}
        for business in self.strategy.search(self.gateway, region):
            unique.setdefault(business.place_id, business)
        return ExtractionResult(
            region, businesses_to_frame(unique.values(), region.name)
        )
