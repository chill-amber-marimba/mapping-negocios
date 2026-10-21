"""Tests for the ``convert`` CLI command."""

import xml.etree.ElementTree as ET
from pathlib import Path

from polars.testing import assert_frame_equal
from typer.testing import CliRunner

from mapping_negocios.application.frames import businesses_to_frame
from mapping_negocios.cli import app
from mapping_negocios.domain.models import Adherencia
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.csv_importer import CsvImporter
from mapping_negocios.infrastructure.kml_exporter import KML_NS

from fakes import make_business

runner = CliRunner()


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
