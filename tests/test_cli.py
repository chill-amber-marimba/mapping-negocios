"""Tests for the CLI commands."""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from typer.testing import CliRunner

from mapping_negocios import cli
from mapping_negocios.application.frames import businesses_to_frame
from mapping_negocios.cli import app
from mapping_negocios.config import API_KEY_ENV
from mapping_negocios.domain.models import Adherencia
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.csv_importer import CsvImporter
from mapping_negocios.infrastructure.kml_exporter import KML_NS

from fakes import FakeGateway, make_business, make_dense_businesses

runner = CliRunner()
GRID_ARGS = ["--grid", "--tile-size-m", "1000", "--max-requests", "3"]


@pytest.fixture
def fake_places(gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    """Make ``extract`` use the fake gateway instead of Google Places."""
    gateway.nearby = make_dense_businesses()
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.setattr(cli, "GooglePlacesClient", lambda api_key: gateway)
    return gateway


def run_extract(out_dir: Path, *extra: str) -> str:
    """Run ``extract --grid`` successfully and return its output."""
    args = ["extract", "Test Town", "--out-dir", str(out_dir), *GRID_ARGS, *extra]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def test_extract_grid_resumes_until_done(
    fake_places: FakeGateway, tmp_path: Path
) -> None:
    """Runs over budget save progress; reruns add the rest and keep CSV edits."""
    progress_path = tmp_path / ".test-town.grid-progress.json"
    csv_path = tmp_path / "test-town.csv"

    assert "budget exhausted" in run_extract(tmp_path)
    assert progress_path.exists()
    first = CsvImporter().read(csv_path)
    edited_id = first["place_id"][0]
    edited = first.with_columns(
        pl.when(pl.col("place_id") == edited_id)
        .then(pl.lit("red"))
        .otherwise(pl.col("adherencia"))
        .cast(first.schema["adherencia"])
        .alias("adherencia")
    )
    CsvExporter().export(edited, csv_path, "ignored")

    for _ in range(20):
        output = run_extract(tmp_path)
        assert "Resuming" in output
        if not progress_path.exists():
            break
    else:
        pytest.fail("grid search never finished")

    final = CsvImporter().read(csv_path)
    assert final["place_id"].n_unique() == final.height == 25
    assert final.filter(pl.col("place_id") == edited_id)["adherencia"][0] == "red"
    # No box is searched twice across the resumed runs.
    calls = fake_places.nearby_calls
    assert len(set(calls)) == len(calls)


def test_extract_grid_rejects_other_options_when_resuming(
    fake_places: FakeGateway, tmp_path: Path
) -> None:
    """Saved progress is not reused for different place types."""
    run_extract(tmp_path)
    args = ["extract", "Test Town", "--out-dir", str(tmp_path), *GRID_ARGS]
    result = runner.invoke(app, [*args, "--type", "cafe"])
    assert result.exit_code == 1
    assert "--restart" in result.output

    assert "Resuming" not in run_extract(tmp_path, "--type", "cafe", "--restart")


def test_extract_grid_needs_previous_csv_to_resume(
    fake_places: FakeGateway, tmp_path: Path
) -> None:
    """Resuming without the previous results fails instead of losing them."""
    run_extract(tmp_path)
    (tmp_path / "test-town.csv").unlink()
    args = ["extract", "Test Town", "--out-dir", str(tmp_path), *GRID_ARGS]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "cannot read previous results" in result.output


def write_csv(path: Path) -> Path:
    """Export two businesses, one with adherencia, as CSV."""
    frame = businesses_to_frame(
        [
            make_business("a", types=("cafe",), adherencia=Adherencia.GREEN),
            make_business("b"),
        ],
        "Test Town",
    )
    return CsvExporter().export(frame, path, "ignored")


def test_convert_csv_to_kml_and_back(tmp_path: Path) -> None:
    """CSV -> KML -> CSV keeps the data; the KML is named after the region."""
    source = write_csv(tmp_path / "in.csv")
    kml = tmp_path / "out" / "map.kml"
    back = tmp_path / "back.csv"

    result = runner.invoke(app, ["convert", str(source), str(kml)])
    assert result.exit_code == 0, result.output
    assert "2 businesses" in result.output
    root = ET.parse(kml).getroot()
    assert root.findtext("k:Document/k:name", namespaces={"k": KML_NS}) == ("Test Town")

    result = runner.invoke(app, ["convert", str(kml), str(back)])
    assert result.exit_code == 0, result.output
    assert_frame_equal(CsvImporter().read(back), CsvImporter().read(source))


def test_convert_rejects_unsupported_extension(tmp_path: Path) -> None:
    """Destinations with an unknown extension fail with a clear message."""
    source = write_csv(tmp_path / "in.csv")
    result = runner.invoke(app, ["convert", str(source), str(tmp_path / "x.json")])
    assert result.exit_code == 1
    assert "unsupported file" in result.output
    assert not (tmp_path / "x.json").exists()


def test_convert_reports_invalid_input(tmp_path: Path) -> None:
    """A malformed source file fails with an error instead of a traceback."""
    source = tmp_path / "broken.kml"
    source.write_text("<kml>not closed")
    result = runner.invoke(app, ["convert", str(source), str(tmp_path / "x.csv")])
    assert result.exit_code == 1
    assert "cannot read" in result.output
