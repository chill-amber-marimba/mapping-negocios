"""Tests for the JSON grid progress store."""

from pathlib import Path

import pytest

from mapping_negocios.application.strategies import GridProgress
from mapping_negocios.infrastructure.grid_progress_store import JsonGridProgressStore

from fakes import REGION


def test_save_load_round_trip(tmp_path: Path) -> None:
    """Saved boxes load back exactly, so they match the tiles of a new run."""
    sw, se, nw, ne = REGION.bounds.quadrants()
    progress = GridProgress(
        REGION.bounds, 812.5, ("cafe", "bar"), completed={sw, se}, saturated={ne}
    )
    store = JsonGridProgressStore(tmp_path / "out" / ".x.json")
    store.save(progress)
    assert store.load() == progress
    assert nw not in progress.completed


def test_load_without_file_returns_none(tmp_path: Path) -> None:
    """No saved progress means a fresh search."""
    assert JsonGridProgressStore(tmp_path / "missing.json").load() is None


def test_clear_deletes_the_file(tmp_path: Path) -> None:
    """Clearing removes the file and tolerates it being gone."""
    store = JsonGridProgressStore(tmp_path / "x.json")
    store.save(GridProgress(REGION.bounds, 1000))
    store.clear()
    store.clear()
    assert not store.path.exists()


@pytest.mark.parametrize(
    "content", ["not json", '{"version": 1}', '{"version": 99}'], ids=str
)
def test_load_rejects_invalid_file(tmp_path: Path, content: str) -> None:
    """Corrupt, incomplete or newer files raise a ValueError."""
    path = tmp_path / "x.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="Invalid grid progress file"):
        JsonGridProgressStore(path).load()
