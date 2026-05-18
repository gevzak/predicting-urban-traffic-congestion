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
