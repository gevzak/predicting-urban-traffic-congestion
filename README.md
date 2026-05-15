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

## Views

The database exposes five SQL views that de-normalise the schema in
[data/create.sql](data/create.sql) into query-ready forms for analysis
and modelling. Definitions are in [data/views.sql](data/views.sql).

### `v_measurements_enriched`

Flat row-per-observation join of `TrafficMeasurements` with `TrafficSites`
and `Calendar`, adding `day_of_week`. Use this when you want every
measurement alongside its site and date context without writing the
joins yourself.

### `v_ml_feature_set`

ML-ready feature table. One row per observation with `flow`, `flow_pc`,
`dsat`, `dsat_pc`, cyclical time encodings (`sin_time`, `cos_time`),
`day_num` (0 = Monday … 6 = Sunday), and a 5-class `target` derived from
per-site `NTILE(5)` over `cong`. Selecting from this view yields the
inputs and labels the classifier consumes.

> Note: per-site target binning here uses MariaDB `NTILE(5)`, which
> always produces five rank-based buckets. The reference notebook uses
> pandas `qcut(..., duplicates='drop')` which collapses tied buckets,
> so labels for sites with sparse non-zero `cong` may differ slightly
> between the two implementations.

### `v_class_balanced_training_sample`

Up to 10 000 rows per `target` class, drawn via
`ROW_NUMBER() OVER (PARTITION BY target ORDER BY RAND())`. Designed for
training when the raw distribution is too skewed (class 0 dominates the
fact table). Same columns as `v_ml_feature_set`.

> Note: `ORDER BY RAND()` re-evaluates on every query, so the sample is
> not stable across calls. For reproducible runs, snapshot the result
> or seed selection client-side.

### `v_hourly_site_aggregates`

Per `(site_id, date_id, hour_of_day)` averages of `flow`, `cong`, `dsat`
and their `*_pc` percentage counterparts, plus `interval_count`. Useful
for daily-profile analysis and richer time-of-day features.

### `v_site_class_distribution`

Per `(site_id, target)` observation counts. Surfaces how class
imbalance varies across sites — helpful for per-site evaluation and for
spotting sites with degenerate class distributions.
