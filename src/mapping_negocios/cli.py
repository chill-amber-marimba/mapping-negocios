"""Command line interface; also the composition root wiring adapters to use cases."""

import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated

import polars as pl
import typer
from rich.console import Console

from mapping_negocios.application.extract import ExtractBusinesses
from mapping_negocios.application.frames import (
    BusinessExporter,
    BusinessImporter,
    merge_businesses,
    summarize_by_type,
)
from mapping_negocios.application.strategies import (
    GridProgress,
    GridSearchStrategy,
    ProgressMismatchError,
    SearchStrategy,
    TextSearchStrategy,
)
from mapping_negocios.config import ConfigError, Settings
from mapping_negocios.domain.models import PlacesApiError, RegionNotFoundError
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.csv_importer import CsvImporter
from mapping_negocios.infrastructure.google_places import GooglePlacesClient
from mapping_negocios.infrastructure.grid_progress_store import JsonGridProgressStore
from mapping_negocios.infrastructure.kml_exporter import KmlExporter
from mapping_negocios.infrastructure.kml_importer import KmlImporter

app = typer.Typer(
    help="Map the businesses of a region using Google Places.", no_args_is_help=True
)
console = Console()

# Adapters by file extension.
EXPORTERS: dict[str, BusinessExporter] = {
    exporter.extension: exporter for exporter in (CsvExporter(), KmlExporter())
}
IMPORTERS: dict[str, BusinessImporter] = {
    importer.extension: importer for importer in (CsvImporter(), KmlImporter())
}
# What a malformed input file can raise while being read.
READ_ERRORS = (pl.exceptions.PolarsError, ET.ParseError, ValueError)


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
    restart: Annotated[
        bool,
        typer.Option(help="Discard saved --grid progress and search from scratch."),
    ] = False,
) -> None:
    """Extract the businesses of REGION into a CSV and an Organic Maps KML.

    When --grid runs out of --max-requests, the boxes already searched are saved
    next to the output; running the same command again continues from there.
    """
    stem = slugify(region)
    store = JsonGridProgressStore(out_dir / f".{stem}.grid-progress.json")
    if restart:
        store.clear()
    grid_strategy: GridSearchStrategy | None = None
    previous: pl.DataFrame | None = None
    if grid:
        progress = _load_progress(store)
        if progress is not None:
            previous = _read_previous(out_dir / f"{stem}.csv", store.path)
            console.print(
                f"Resuming: skipping {len(progress.completed)} searched boxes "
                f"and keeping {previous.height} businesses."
            )
        grid_strategy = GridSearchStrategy(
            tile_size_m, place_type or (), max_depth, max_requests, progress
        )
    strategy: SearchStrategy = (
        grid_strategy if grid_strategy is not None else TextSearchStrategy(query)
    )
    try:
        gateway = GooglePlacesClient(Settings.from_env().google_maps_api_key)
        result = ExtractBusinesses(gateway, strategy)(region)
    except (ConfigError, PlacesApiError, RegionNotFoundError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except ProgressMismatchError as exc:
        console.print(
            f"[red]Error:[/red] {exc} Use the same options, or --restart "
            f"to discard {store.path}."
        )
        raise typer.Exit(code=1) from exc

    businesses = (
        result.businesses
        if previous is None
        else merge_businesses(previous, result.businesses)
    )
    for exporter in EXPORTERS.values():
        written = exporter.export(
            businesses, out_dir / f"{stem}.{exporter.extension}", result.region.name
        )
        console.print(f"Wrote {written}")

    console.print(f"{businesses.height} businesses in {result.region.name}")
    console.print(summarize_by_type(businesses))
    if grid_strategy is not None and grid_strategy.progress is not None:
        if grid_strategy.budget_exhausted:
            saved = store.save(grid_strategy.progress)
            console.print(
                f"[yellow]Request budget exhausted:[/yellow] progress saved to "
                f"{saved}. Run the same command again to continue."
            )
        else:
            store.clear()


def _load_progress(store: JsonGridProgressStore) -> GridProgress | None:
    """Load saved grid progress or exit with an error if it is unreadable."""
    try:
        return store.load()
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc} Use --restart to discard it.")
        raise typer.Exit(code=1) from exc


def _read_previous(csv_path: Path, progress_path: Path) -> pl.DataFrame:
    """Read the businesses of the run being resumed or exit with an error."""
    try:
        return CsvImporter().read(csv_path)
    except (FileNotFoundError, *READ_ERRORS) as exc:
        console.print(
            f"[red]Error:[/red] cannot read previous results {csv_path} to resume "
            f"from {progress_path}: {exc} Restore it, or use --restart."
        )
        raise typer.Exit(code=1) from exc


@app.command()
def convert(
    source: Annotated[
        Path,
        typer.Argument(help="CSV or KML file to read.", exists=True, dir_okay=False),
    ],
    destination: Annotated[
        Path,
        typer.Argument(help="CSV or KML file to write; format from its extension."),
    ],
) -> None:
    """Convert a businesses file from KML to CSV or from CSV to KML."""
    importer = _adapter_for(IMPORTERS, source)
    exporter = _adapter_for(EXPORTERS, destination)
    try:
        frame = importer.read(source)
    except READ_ERRORS as exc:
        console.print(f"[red]Error:[/red] cannot read {source}: {exc}")
        raise typer.Exit(code=1) from exc

    written = exporter.export(frame, destination, _title(frame, source))
    console.print(f"Wrote {written} ({frame.height} businesses)")


def _adapter_for[A](adapters: dict[str, A], path: Path) -> A:
    """Pick the adapter for ``path``'s extension or exit with an error."""
    try:
        return adapters[path.suffix.lower().removeprefix(".")]
    except KeyError:
        supported = ", ".join(f".{ext}" for ext in adapters)
        console.print(
            f"[red]Error:[/red] unsupported file {path.name!r}; use {supported}."
        )
        raise typer.Exit(code=1) from None


def _title(frame: pl.DataFrame, source: Path) -> str:
    """Name the output after the searched region, falling back to the file name."""
    regions = frame["search_region"].drop_nulls()
    return regions[0] if regions.len() else source.stem
