"""JSON file storing the progress of a budget-limited grid search."""

import json
from pathlib import Path
from typing import Any

from mapping_negocios.application.strategies import GridProgress
from mapping_negocios.domain.models import BoundingBox

FORMAT_VERSION = 1


class JsonGridProgressStore:
    """Saves, loads and clears ``GridProgress`` in a single JSON file."""

    def __init__(self, path: Path) -> None:
        """Store progress at ``path``."""
        self.path = path

    def load(self) -> GridProgress | None:
        """Read the saved progress.

        Returns:
            The saved progress, or None if there is none.

        Raises:
            ValueError: If the file is not valid progress JSON.
        """
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["version"] != FORMAT_VERSION:
                raise ValueError(f"unsupported version {data['version']}")
            return GridProgress(
                region_bounds=_box(data["region_bounds"]),
                tile_size_m=float(data["tile_size_m"]),
                included_types=tuple(data["included_types"]),
                completed={_box(b) for b in data["completed"]},
                saturated={_box(b) for b in data["saturated"]},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid grid progress file {self.path}: {exc}") from exc

    def save(self, progress: GridProgress) -> Path:
        """Write ``progress``, replacing any saved one.

        Args:
            progress: Progress to save.

        Returns:
            The written path.
        """
        data = {
            "version": FORMAT_VERSION,
            "region_bounds": _coords(progress.region_bounds),
            "tile_size_m": progress.tile_size_m,
            "included_types": list(progress.included_types),
            "completed": sorted(_coords(b) for b in progress.completed),
            "saturated": sorted(_coords(b) for b in progress.saturated),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return self.path

    def clear(self) -> None:
        """Delete the saved progress, if any."""
        self.path.unlink(missing_ok=True)


def _coords(box: BoundingBox) -> list[float]:
    return [box.south, box.west, box.north, box.east]


def _box(coords: Any) -> BoundingBox:  # noqa: ANN401 - untyped JSON
    south, west, north, east = coords
    return BoundingBox(float(south), float(west), float(north), float(east))
