"""CSV exporter."""

from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import LIST_SEPARATOR


class CsvExporter:
    """Writes the businesses DataFrame to a UTF-8 CSV file."""

    extension = "csv"

    def export(self, frame: pl.DataFrame, path: Path, title: str) -> Path:
        """Write ``frame`` as CSV, joining list columns with ``|``.

        Args:
            frame: Businesses DataFrame.
            path: Destination file.
            title: Unused; part of the exporter interface.

        Returns:
            The written path.
        """
        list_cols = [
            name for name, dtype in frame.schema.items() if isinstance(dtype, pl.List)
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.with_columns(pl.col(list_cols).list.join(LIST_SEPARATOR)).write_csv(path)
        return path
