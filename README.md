# Predicting Urban Traffic Congestion Levels using Multi-Layer Perceptrons on SDCC SCOOT Data

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20365705.svg)](https://doi.org/10.5281/zenodo.20365705)

## Citation

If you use this software, please cite the archived release on Zenodo
(see [`CITATION.cff`](CITATION.cff)). The concept DOI
[10.5281/zenodo.20365705](https://doi.org/10.5281/zenodo.20365705)
always resolves to the latest release. The release was minted via the
GitHub–Zenodo integration, so each tagged GitHub release archives a new
version automatically.

## Abstract

This experiment aims to classify traffic congestion levels across South Dublin County. Using
the *Traffic Flow Data Jan to June 2022 SDCC* dataset, which contains high-resolution (15-minute)
measurements of flow, saturation (`dsat`), and congestion (`cong`), I engineered a 5-tier classification
system (Free Flow (0) to Severe Congestion (5)) based on site-specific quantiles. A Multi-Layer
Perceptron (MLP) was implemented using TensorFlow to predict these categories. Despite a heavy
class imbalance (93% Free Flow), the model was optimized using class-weighting and cyclical time
encoding. The results demonstrate the feasibility of using SCOOT-derived metrics to provide early
warnings for traffic management systems.

## Requirements and Installation

Requirements are separated into `requirements/local.txt` and `requirements/colab.txt`. For former contains libraries
that are required for notebooks and python scripts that can be run locally. The latter contains libraries required for
running the full ML pipeline on Google Colab: `01_sdcc_traffic_full_pipeline_mlp.ipynb`and `dbrepo_loader.py`. The ML
pipeline can be run by following the steps below:

1. From [Google Colab](https://colab.research.google.com/) click on Upload on the left menu of the pop-up. Then upload
`notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb`. 
2. Click on Files (![](images/folder_icon.png)) on the left-most menu. 
3. Click on Upload to session storage (![](images/upload_icon.png)) under the Files menu.
   - Dragging files into the Files menu is also an option.
4. Upload `src/dbrepo_loader.py`, `requirements/colab.txt`, `config_mlp_v1.yaml`, and `.env`. Ensure that all variables 
are properly defined in `.env`.
5. Run the notebook.
   - Note that loading the data from dbrepo will likely fail. If it does, keep rerunning the cell until the data is 
   successfully loaded. This may take more than 10 attempts. 

## Reproduction Instructions

Exact reproducibility cannot be guranteed due to floating-point non-determinism in parallel GPU execution.
Reproducibility can be guranteed by training on CPU. However, this was not done due to the long wall times for training.

Models can be re-created by reading the appropriate FAIR4ML metadata at [Insert TUWRD Model DOI Link from T3.9] and adjusting 
`config_mlp_v1.yaml` accordingly. The trained models will be funtionally equivalent in performance metrics, but weights
and predictions are not guranteed to be numerically identical.

## Description of Inputs and Outputs

### Ingestion Inputs
* **Training Source Data:** `v_measurements_enriched` (Fetched via DBRepo). Originating platform identifier: 
`e3a592bf-1342-4150-b8ae-4ca7a89f2c70` (Traffic Flow Data Jan to June 2022 SDCC).
* **Dataset Schema & Units:** `croissant.json` — Maps data layers to QUDT semantic units.
* **Pipeline Source Code:** Python training notebooks, relevant scripts, and dependencies pinned via `codemeta.json`.

### Preserved Outputs
* **Trained Model Checkpoint:** `outputs/models/` — Deep learning classifier weights. Registered at TUWRD: 
[Insert TUWRD Model DOI Link from T3.9].
* **Model Metadata:** `mlp_classifier_v1.json` — Compliant machine-readable asset tracking sheet. Registered at TUWRD: 
[Insert TUWRD Model DOI Link from T3.9]
* **Performance Evaluation Records:** Plots (`outputs/figures/`). Registered at TUWRD: 
[Insert TUWRD Generated Data DOI Link from T3.10].
* **Human Documentation:** `docs/model-card.md` — Contextual overview of risks and evaluation benchmarks.

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
│   ├── processed
│   ├── raw
├── docs
│   ├── superpowers
│   ├── plans
│   └── specs
├── notebooks
├── outputs
│   ├── figures
│   └── models
├── requirements
└── src
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

## Metadata

[`croissant.json`](croissant.json) at the repo root is a Croissant 1.0
JSON-LD metadata record describing the input dataset, its source CSV
distribution, and the field-level schema (data types and QUDT unit URIs
for numeric attributes) across the three tables (Calendar, TrafficSites,
TrafficMeasurements).

DBRepo's column-level unit annotations use OM-2 URIs (set at the time
the data was ingested). The Croissant record uses QUDT URIs. The two
ontologies are equivalent for the units in question (percent,
dimensionless count); the choice reflects the convention of each
target ecosystem. Both records are authoritative for their respective
catalogue.

Validate the Croissant record with:

```bash
mlcroissant validate --jsonld croissant.json
```

## Licenses

### Input Data
**Source**: South Dublin County Council (SDCC) Traffic Flow Data (January–June 2022), obtained from data.europa.eu.
- **Licence**: Creative Commons Attribution 4.0 International (CC BY 4.0), SPDX identifier: `CC-BY-4.0`.
- **Verification of permitted use**: The CC BY 4.0 licence permits use for academic research, machine learning model development, and the creation of derived works.
- **Obligations**: The licence requires attribution to the original source. It does not include ShareAlike provisions, meaning derived works may be licensed under compatible terms without mandatory copyleft restrictions.

### Software / Code
- **Licence**: MIT Licence, SPDX identifier: `MIT`. The full licence text is provided in the `LICENSE` file in the repository root.
- **Justification**: The MIT Licence was selected for its permissiveness, simplicity, and widespread adoption in academic and open-source software projects.
- **Compatibility with input data licence**: The MIT Licence is compatible with CC BY 4.0 because both licences impose only attribution requirements and contain no ShareAlike or copyleft provisions. This ensures the software can legally process CC BY 4.0-licensed data without licensing conflicts.

### Output Data
- **Licence**: Creative Commons Attribution 4.0 International (CC BY 4.0), SPDX identifier: `CC-BY-4.0`.

## Contributors with ORCIDs

- Habib Ahmad - 0009-0002-0332-2702
- Johannes Held - 
- Kyzer Gerez - 0000-0003-4463-3929
- Gevorg Zakaryan - 0009-0002-8980-8948
