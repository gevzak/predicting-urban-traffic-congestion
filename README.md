# Predicting Urban Traffic Congestion

## File Organization

This repository follows a structured naming convention aligned with the traffic congestion classification pipeline.

**General format:**

```
<project>_<stage>_<description>_<version>.<extension>
```
* project: sdcc_traffic
* stage: raw, target, features, model, fig, etc.
* description: brief explanation of contents
* version: version number (v1, v2, …)

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
├── outputs
    ├── figures
    └── models
```

## Views (T2.4)

Five SQL views de-normalise the 3NF schema (defined in
[data/create.sql](data/create.sql)) into query-ready forms for the ML
pipeline and downstream API consumption. Definitions live in
[data/views.sql](data/views.sql); the views are created in DBRepo by
Owner C as part of T2.5 (data load + verification).

### `v_measurements_enriched`

- **Contains:** one row per traffic measurement, flat-joined with its site
  (from `TrafficSites`) and its calendar entry (from `Calendar`). Adds
  `day_of_week` alongside the original measurement columns.
- **Why it exists:** the 3NF schema splits every observation across three
  tables. Any analysis touching time or site context has to join all
  three. This view does the join once.
- **Helps the ML pipeline:** acts as the foundation for `v_ml_feature_set`
  (and any future feature views) so feature engineering doesn't have to
  re-state the join. Also serves as a generic "give me everything as one
  table" endpoint for ad-hoc exploration.

### `v_ml_feature_set`

- **Contains:** one row per observation with the seven features used by
  the classifier — `flow`, `flow_pc`, `dsat`, `dsat_pc`, `sin_time`,
  `cos_time`, `day_num` — plus a 5-class `target` derived from per-site
  quantile binning of `cong` via MariaDB `NTILE(5)`.
- **Why it exists:** the model in
  [notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb](notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb)
  consumes exactly this feature set. Computing `sin_time`/`cos_time`,
  `day_num`, and the per-site target in SQL makes the labels
  deterministic and reproducible for every consumer of the database.
- **Helps the ML pipeline:** T2.6 can replace the notebook's Python
  feature-engineering block with a single `SELECT * FROM
  v_ml_feature_set` call, removing all local file reads and ensuring
  every run sees identical labels.
- **Caveat:** MariaDB `NTILE(5)` always produces exactly five rank-based
  buckets and may split tied values across buckets. The original
  notebook uses pandas `qcut(..., duplicates='drop')`, which collapses
  buckets when many tied values exist. For sites with sparse non-zero
  `cong`, class labels may therefore differ slightly between the two
  implementations.

### `v_class_balanced_training_sample`

- **Contains:** up to 10 000 rows per `target` class (≤ 50 000 rows total),
  drawn via `ROW_NUMBER() OVER (PARTITION BY target ORDER BY RAND())`.
  Same columns as `v_ml_feature_set`.
- **Why it exists:** class 0 ("no congestion") accounts for roughly 70%
  of all observations. Training on the raw distribution biases the model
  toward predicting class 0. A pre-balanced view lets the ML pipeline
  pull a usable training set in one query.
- **Helps the ML pipeline:** removes the need for in-Python resampling
  or `class_weight='balanced'` tricks — the dataset is already balanced
  at the source.
- **Caveat:** `ORDER BY RAND()` is re-evaluated on every query, so the
  sample is not stable across calls. If reproducibility is required for
  T2.6 evaluation, snapshot the result to a file or use a seeded selector.

### `v_hourly_site_aggregates`

- **Contains:** per `(site_id, date_id, hour_of_day)` row with averages of
  `flow`, `cong`, `dsat` and their `*_pc` percentage counterparts, plus
  `interval_count` (number of 15-minute intervals aggregated).
- **Why it exists:** the raw fact table records measurements every 15
  minutes. Many downstream questions ("which hours are busiest at site
  X?", "what's the typical daily profile?") need hourly granularity.
  Aggregating once in a view is faster than re-aggregating in Python on
  every notebook restart.
- **Helps the ML pipeline:** supplies pre-computed hourly statistics
  that can be joined into the feature set for richer time-of-day
  features in future model iterations.

### `v_site_class_distribution`

- **Contains:** per `(site_id, target)` row with `observation_count`.
- **Why it exists:** class imbalance varies sharply across sites — some
  sites see almost no congestion, others see heavy congestion most of
  the day. A view exposes this diagnostic directly.
- **Helps the ML pipeline:** supports evaluation slicing (per-site
  recall on the rarer classes) and surfaces sites with degenerate class
  distributions that may need to be excluded from training.
