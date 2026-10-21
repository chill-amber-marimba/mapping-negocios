"""Dagger CI/CD pipeline for mapping-negocios.

Examples:
    dagger call check
    dagger call extract --api-key=env:GOOGLE_MAPS_API_KEY \
        --region="Chamberí, Madrid" export --path=./output
"""

import asyncio
from typing import Annotated

import dagger
from dagger import DefaultPath, Doc, Ignore, dag, function, object_type

PYTHON_IMAGE = "python:3.12-slim"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.13.1"
WORKDIR = "/app"
OUTPUT_DIR = f"{WORKDIR}/output"

Source = Annotated[
    dagger.Directory,
    DefaultPath("/"),
    Ignore([".venv", ".git", ".dagger", "output", ".ruff_cache", "**/__pycache__"]),
    Doc("Project source directory"),
]


@object_type
class MappingNegocios:
    """CI checks and containerized extraction for mapping-negocios."""

    @function
    def base(self, source: Source) -> dagger.Container:
        """Python container with uv and the project's locked dependencies."""
        uv = dag.container().from_(UV_IMAGE).directory("/")
        return (
            dag.container()
            .from_(PYTHON_IMAGE)
            .with_directory("/usr/local/bin", uv, include=["uv", "uvx"])
            .with_env_variable("UV_LINK_MODE", "copy")
            .with_env_variable("UV_PYTHON_DOWNLOADS", "never")
            .with_mounted_cache("/root/.cache/uv", dag.cache_volume("uv-cache"))
            .with_workdir(WORKDIR)
            # Install dependencies first so this layer is cached across code changes.
            .with_file("pyproject.toml", source.file("pyproject.toml"))
            .with_file("uv.lock", source.file("uv.lock"))
            .with_file("README.md", source.file("README.md"))
            .with_exec(["uv", "sync", "--frozen", "--no-install-project"])
            .with_directory(".", source)
            .with_exec(["uv", "sync", "--frozen"])
        )

    @function
    async def lint(self, source: Source) -> str:
        """Run ruff linter and formatter check."""
        return await (
            self.base(source)
            .with_exec(["uv", "run", "ruff", "check", "."])
            .with_exec(["uv", "run", "ruff", "format", "--check", "."])
            .stdout()
        )

    @function
    async def typecheck(self, source: Source) -> str:
        """Run pyrefly type checker."""
        return (
            await self.base(source)
            .with_exec(["uv", "run", "pyrefly", "check"])
            .stdout()
        )

    @function
    async def test(self, source: Source) -> str:
        """Run the pytest suite."""
        return await self.base(source).with_exec(["uv", "run", "pytest"]).stdout()

    @function
    async def check(self, source: Source) -> str:
        """Run lint, typecheck and tests concurrently; fails if any fails."""
        results = await asyncio.gather(
            self.lint(source), self.typecheck(source), self.test(source)
        )
        return "\n".join(results)

    @function
    def extract(
        self,
        source: Source,
        api_key: Annotated[dagger.Secret, Doc("Google Maps API key")],
        region: Annotated[str, Doc("Region name, e.g. 'Chamberí, Madrid'")],
        grid: Annotated[bool, Doc("Use thorough grid search")] = False,
        query: Annotated[str, Doc("Text search query")] = "businesses",
        types: Annotated[list[str] | None, Doc("Place types for grid search")] = None,
        tile_size_m: Annotated[float, Doc("Grid tile size in meters")] = 1000.0,
        max_requests: Annotated[int, Doc("Grid API request budget")] = 200,
    ) -> dagger.Directory:
        """Extract businesses of a region; returns a directory with CSV and KML."""
        args = ["uv", "run", "mapping-negocios", "extract", region]
        args += ["--out-dir", OUTPUT_DIR, "--query", query]
        args += ["--tile-size-m", str(tile_size_m), "--max-requests", str(max_requests)]
        if grid:
            args.append("--grid")
        for place_type in types or []:
            args += ["--type", place_type]
        return (
            self.base(source)
            .with_secret_variable("GOOGLE_MAPS_API_KEY", api_key)
            .with_exec(args)
            .directory(OUTPUT_DIR)
        )
