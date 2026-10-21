"""Command line interface; also the composition root wiring adapters to use cases."""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from mapping_negocios.application.extract import ExtractBusinesses
from mapping_negocios.application.frames import BusinessExporter, summarize_by_type
from mapping_negocios.application.strategies import (
    GridSearchStrategy,
    SearchStrategy,
    TextSearchStrategy,
)
from mapping_negocios.config import ConfigError, Settings
from mapping_negocios.domain.models import PlacesApiError, RegionNotFoundError
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.google_places import GooglePlacesClient
from mapping_negocios.infrastructure.kml_exporter import KmlExporter

app = typer.Typer(
    help="Map the businesses of a region using Google Places.", no_args_is_help=True
)
console = Console()


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)


def slugify(text: str) -> str:
    """Turn text into a lowercase ASCII file-name friendly slug.

    Args:
        text: Any text, e.g. ``"Chamberí, Madrid"``.

    Returns:
        A slug such as ``"chamberi-madrid"``.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "region"


@app.command()
def extract(
    region: Annotated[
        str, typer.Argument(help="Region name, e.g. 'Chamberí, Madrid'.")
    ],
    out_dir: Annotated[Path, typer.Option(help="Output directory.")] = Path("output"),
    grid: Annotated[
        bool,
        typer.Option(
            help="Thorough grid search (more API calls) instead of text search."
        ),
    ] = False,
    query: Annotated[
        str, typer.Option(help="Text search query (default mode).")
    ] = "businesses",
    place_type: Annotated[
        list[str] | None,
        typer.Option("--type", help="Place type filter for --grid; repeatable."),
    ] = None,
    tile_size_m: Annotated[
        float, typer.Option(help="Grid tile size in meters.")
    ] = 1000.0,
    max_depth: Annotated[
        int, typer.Option(help="Max subdivisions of saturated tiles.")
    ] = 3,
    max_requests: Annotated[int, typer.Option(help="Grid API request budget.")] = 200,
) -> None:
    """Extract the businesses of REGION into a CSV and an Organic Maps KML."""
    strategy: SearchStrategy = (
        GridSearchStrategy(tile_size_m, place_type or (), max_depth, max_requests)
        if grid
        else TextSearchStrategy(query)
    )
    try:
        gateway = GooglePlacesClient(Settings.from_env().google_maps_api_key)
        result = ExtractBusinesses(gateway, strategy)(region)
    except (ConfigError, PlacesApiError, RegionNotFoundError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    exporters: list[BusinessExporter] = [CsvExporter(), KmlExporter()]
    stem = slugify(region)
    for exporter in exporters:
        written = exporter.export(
            result.businesses,
            out_dir / f"{stem}.{exporter.extension}",
            result.region.name,
        )
        console.print(f"Wrote {written}")

    console.print(f"{result.businesses.height} businesses in {result.region.name}")
    console.print(summarize_by_type(result.businesses))
