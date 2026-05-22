# Predicting Urban Traffic Congestion

## File Organization

This repository follows a structured naming convention aligned with the traffic congestion classification pipeline.

**General format:**

```
<project>_<stage>_<description>.<extension>
```
* project: sdcc_traffic
* stage: raw, target, features, model, fig, etc.
* description: brief explanation of contents

For configuration files, it will be simplified down to

```
config_mlp_<version>.yaml
```

The repository folder structure is depicted below.

```md
├── data
│   ├── processed
│   └── raw 
├── docs
├── notebooks
└── outputs
    ├── figures
    └── models
```

## Views

The database exposes three SQL views that de-normalise the schema in
[data/create.sql](data/create.sql) into query-ready slices. Definitions
live in [data/views.sql](data/views.sql) and are created in DBRepo by
[notebooks/create-views-DBrepo-notebook.ipynb](notebooks/create-views-DBrepo-notebook.ipynb).

All three views are inner joins of `TrafficMeasurements`, `Calendar`, and
`TrafficSites`, with optional `WHERE` filters. They are expressible in
DBRepo's structured query model, so they can be created via the REST API
and consumed through DBRepo's view-data endpoints. Feature engineering
that requires computed columns, window functions, or aggregations —
cyclical time encoding, the 5-class congestion target, class-balanced
sampling, hourly aggregation — is performed downstream in Python after
fetching from these views.

### `v_measurements_enriched`

- **Contains:** one row per measurement with `day_of_week` joined in from
  `Calendar` alongside the original metric columns
  (`flow`, `flow_pc`, `cong`, `cong_pc`, `dsat`, `dsat_pc`,
  `start_time`, `end_time`).
- **Why it exists:** the 3NF schema spreads every observation across three
  tables. Any analysis touching the calendar or site has to re-state the
  join. This view does it once.
- **Helps the ML pipeline:** acts as the general-purpose data source —
  the Python pipeline pulls from this view and computes its own features
  (`sin_time`, `cos_time`, `day_num`, target class).

### `v_weekday_measurements`

- **Contains:** the same columns as `v_measurements_enriched`, filtered
  to rows where `day_of_week` is not `Saturday` or `Sunday`.
- **Why it exists:** weekend traffic patterns differ markedly from
  weekday patterns; a weekday-only slice is a reasonable default for
  training and evaluating the congestion classifier.
- **Helps the ML pipeline:** lets the pipeline pull a weekday-only
  training subset in one request, without filtering in pandas
  after the fact.

## DBRepo API access

The experiment loads data from the TU Wien DBRepo REST API only — no local
CSVs are read by the experiment notebook.

- **Base URL:** `https://test.dbrepo.tuwien.ac.at` (configurable via the
  `DBREPO_ENDPOINT` value in `.env`).
- **Client library:** `dbrepo` Python SDK (`RestClient`), which wraps the
  DBRepo REST API.
- **Endpoints used (through the SDK):**
  - `GET /api/database`                              — list databases (auth + connectivity probe)
  - `GET /api/database/{id}/view`                    — list views in a database
  - `GET /api/database/{id}/view/{vid}/data`         — fetch view rows (paged)
  - `GET /api/database/{id}/view/{vid}/data/count`   — view row count
- **Views consumed:** `v_measurements_enriched` is the main data source for
  the experiment notebook. `v_weekday_measurements` is also registered and
  available for weekday-only slices.
- **Authentication:** TU Wien DBRepo username + password.
  Username read from `DBREPO_USERNAME` in `.env`; password resolved from
  the `DBREPO_PASSWORD` env var if set, otherwise prompted interactively via
  `getpass`. The `.env` file is in `.gitignore`.
- **Loader module:** [`src/dbrepo_loader.py`](src/dbrepo_loader.py).
  `load_view(name)` returns a typed `pandas.DataFrame` with view-native
  column names and integer columns coerced back from DBRepo's text
  representation. Typed exceptions (`DBRepoConfigError`, `DBRepoAuthError`,
  `DBRepoConnectionError`, `DBRepoViewNotFound`) let callers translate
  failures into clear diagnostics.
- **Parity check:** [`src/compare_csv_vs_dbrepo.py`](src/compare_csv_vs_dbrepo.py)
  verifies the DBRepo view returns the same data as the original CSV
  source. Run it with:
  ```bash
  python src/compare_csv_vs_dbrepo.py
  ```
  Exit codes: `0` = identical, `1` = data mismatch (the 5-step diagnostic
  report identifies the failing step), `2` = infrastructure failure
  (connection, auth, config, missing view). Use `--limit N` for a fast
  sanity check; use `--dump-diff PATH` to write the full per-row diff to a
  CSV when a mismatch occurs.
