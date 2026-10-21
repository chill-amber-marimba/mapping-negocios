"""CSV importer, the inverse of ``CsvExporter``."""

from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import FLAT_BUSINESS_SCHEMA, unflatten


class CsvImporter:
    """Reads a businesses CSV back into a DataFrame."""

    extension = "csv"

    def read(self, path: Path) -> pl.DataFrame:
        """Read ``path`` forcing the expected schema.

        Args:
            path: CSV file written by ``CsvExporter``.

        Returns:
            A DataFrame with ``BUSINESS_SCHEMA``.

        Raises:
            polars.exceptions.ComputeError: If a value does not fit its column
                type, e.g. an unknown ``adherencia``.
        """
        return unflatten(pl.read_csv(path, schema=FLAT_BUSINESS_SCHEMA))
