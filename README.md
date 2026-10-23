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

```
Options
│ --verbose             -v
│ --help                          Show this message and exit.

Commands
│ extract  Extract the businesses of REGION into a CSV and an Organic Maps KML.
│ convert  Convert a businesses file from KML to CSV or from CSV to KML.
```


### Extract

```
Arguments
│ *    region      <str>  Region name, e.g. 'Chamberí, Madrid'. [required]

Options
│ --out-dir                          <path>   Output directory. [default: output]
│ --grid             --no-grid                Thorough grid search (more API calls) instead of text search. [default: no-grid]
│ --query                            <str>    Text search query (default mode). [default: businesses]
│ --type                             <str>    Place type filter for --grid; repeatable.
│ --tile-size-m                      <float>  Grid tile size in meters. [default: 1000.0]
│ --max-depth                        <int>    Max subdivisions of saturated tiles. [default: 3]
│ --max-requests                     <int>    Grid API request budget. [default: 200]
│ --restart          --no-restart             Discard saved --grid progress and search from scratch. [default: no-restart]
│ --color-by-type                             Color KML pins by business type instead of adherencia.
│ --help                                      Show this message and exit.
```

#### Example

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

#### Resuming a grid search

When `--grid` runs out of `--max-requests`, the boxes already searched are saved
to `output/.chamberi-madrid.grid-progress.json`. Run **the same command** again
(e.g. the next day, or with a new budget) to search only the remaining boxes:
new businesses are added to the existing CSV, whose rows (and any `adherencia`
you filled in) are kept. The progress file is deleted once the region is fully
searched. Changing the tile size or `--type`s requires `--restart`, which
discards the saved progress and searches from scratch.

### Convert

Convert between formats (the format comes from each file's extension).

```
Arguments
│ *    source           <file>  CSV or KML file to read. [required]
│ *    destination      <path>  CSV or KML file to write; format from its extension. [required]

Options
│ --color-by-type          Color KML pins by business type instead of adherencia.
│ --help                   Show this message and exit.
```

#### Example

To regenerate the map after filling in `adherencia` in the CSV:

```bash
uv run mapping-negocios convert output/chamberi-madrid.csv output/chamberi-madrid.kml
uv run mapping-negocios convert output/chamberi-madrid.kml output/chamberi-madrid.csv
```

### Output CSV Columns

`place_id, name, primary_type, types, latitude, longitude, formatted_address,
postal_code, locality, admin_region, country, phone, website, rating,
user_rating_count, business_status, google_maps_uri, search_region, adherencia`
(`types` is `|`-separated in the CSV). `adherencia` is a semaphore
(`green`, `yellow`, `red`), empty until assessed.

### Opening the output map in Organic Maps - Recommended

Copy the `.kml` to your phone (AirDrop, cloud drive, e-mail…), open it and
choose **Organic Maps**. It is imported as a bookmark list named after the
region, stored locally on the device only. Pins are colored by `adherencia`:
green, yellow or red, and gray when not assessed yet.

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
