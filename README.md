# mapping-negocios

Pull the businesses of a region from **Google Places API** into a
**Polars** DataFrame, then export them as a **CSV** and a **KML** that [Organic
Maps](https://organicmaps.app) imports as a private, offline bookmark list.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/#installing-uv)
- (optional) [Docker](https://www.docker.com/get-started/)
- (optional) [dagger.io](https://docs.dagger.io/getting-started/install/)

## Setup

1. Get a GMaps API key (e.g.: the free [Demo API Key](https://developers.google.com/maps/documentation/javascript/demo-key))
2. Install and configure:

```bash
uv sync
export GOOGLE_MAPS_API_KEY=...
```

## Usage

### Extract

```bash
# Default: Text Search, cheap (≤ 3 requests, max 60 results)
uv run mapping-negocios extract "Chamberí, Madrid"
uv run mapping-negocios extract "Chamberí, Madrid" --query "cafés"

# Thorough: grid of Nearby Searches, saturated tiles are split into quadrants
uv run mapping-negocios extract "Chamberí, Madrid" --grid \
    --type restaurant --type cafe --tile-size-m 800 --max-requests 300
```

Output: `output/chamberi-madrid.csv` and `output/chamberi-madrid.kml`.

| Mode | API calls | Coverage |
|---|---|---|
| default (text) | ≤ 3 + 1 geocode | ≤ 60 results, ranked by relevance |
| `--grid` | 1 per tile (+4 per saturated tile) up to `--max-requests` | near complete |

> **Cost:** billing depends on the field mask (`infrastructure/google_places.py`).
> Contact fields (phone, website) and rating use higher-priced SKUs. Use
> `--max-requests` to cap grid searches.

### Output Columns

`place_id, name, primary_type, types, latitude, longitude, formatted_address,
postal_code, locality, admin_region, country, phone, website, rating,
user_rating_count, business_status, google_maps_uri, search_region, adherencia`
(`types` is `|`-separated in the CSV). `adherencia` is a semaphore
(`green`, `yellow`, `red`), empty until assessed.

### Opening the output map in Organic Maps

Copy the `.kml` to your phone (AirDrop, cloud drive, e-mail…), open it and
choose **Organic Maps**. It is imported as a bookmark list named after the
region, stored locally on the device only. Pins are colored by `adherencia`:
green, yellow or red, and gray when not assessed yet.

### Convert

Convert between formats (the format comes from each file's extension), e.g.
to regenerate the map after filling in `adherencia` in the CSV:

```bash
uv run mapping-negocios convert output/chamberi-madrid.csv output/chamberi-madrid.kml
uv run mapping-negocios convert output/chamberi-madrid.kml output/chamberi-madrid.csv
```

## Contribute

### Development

```bash
uv run pytest            # tests (no network; HTTP is mocked)
uv run ruff check . && uv run ruff format --check .
uv run pyrefly check
prek install             # pre-commit hooks
```

Tests follow pytest's good integration practices: src layout, `tests/` outside
the package, `--import-mode=importlib`, package imported from uv's editable
install. Shared fakes live in `tests/fakes.py`.

### CI with Dagger

```bash
dagger call check        # lint + typecheck + test, concurrently in containers
dagger call lint | typecheck | test

# Run the extraction in a container; the key is passed as a Dagger secret
dagger call extract --api-key=env:GOOGLE_MAPS_API_KEY \
    --region="Chamberí, Madrid" --grid --types=cafe \
    export --path=./output
```

### Architecture

Clean architecture: dependencies point inwards only.

```
cli.py (composition root)  ──►  application  ──►  domain
        │                          ▲
        └──►  infrastructure ──────┘ (implements ports)
```

| Layer | Contents |
|---|---|
| `domain/` | Entities and value objects (`Business`, `BoundingBox`…), `PlacesGateway` port. No dependencies. |
| `application/` | `ExtractBusinesses` use case, search strategies, Polars schema/transforms, `BusinessExporter` and `BusinessImporter` ports. |
| `infrastructure/` | Google Places HTTP client, CSV and KML exporters and importers. |
| `cli.py` | Typer CLI wiring concrete adapters. |

If desired, adding this code to a FastAPI endpoint or an ETL task, could be as
easy as writting a new composition root that builds `ExtractBusinesses(gateway,
strategy)` and calls it. New data sources or output formats are new adapters
implementing the ports.
