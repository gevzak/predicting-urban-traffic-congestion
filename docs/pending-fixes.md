# Pending Fixes & Follow-ups

Working notes — delete this file once everything below is closed.

## 1. Upstream blocker: data-upload notebook

Two issues in [notebooks/upload-data-DBrepo-notebook.ipynb](../notebooks/upload-data-DBrepo-notebook.ipynb)
need to be addressed before the views in [data/views.sql](../data/views.sql)
can be created in DBRepo.

### 1.1 `start_time` missing from `TrafficMeasurements`

The schema in [data/create.sql](../data/create.sql) declares `start_time TIME`,
but the dataframe used to build the DBRepo table omits the column. Find this
cell:

```python
df_measurements = df_raw[[
    'site', 'date', 'end_time', 'flow', 'flow_pc',
    'cong', 'cong_pc', 'dsat', 'dsat_pc'
]].copy()
```

Replace with:

```python
df_measurements = df_raw[[
    'site', 'date', 'start_time', 'end_time', 'flow', 'flow_pc',
    'cong', 'cong_pc', 'dsat', 'dsat_pc'
]].copy()
```

Then delete the existing `TrafficMeasurements` in DBRepo (uncomment the
`client.delete_table(DATABASE_ID, "<table-id>")` cell, plug in the
current table id, run, re-comment) and re-run the upload cell.

The upload log should now warn about `start_time` alongside the other
text columns:
```
WARNING default to 'text' for column start_time ...
```

### 1.2 NaN-date inconsistency between `Calendar` and `TrafficMeasurements`

Raw CSV: 73 unique dates, including one row whose `date` is `NaN`.

`Calendar` build drops the `NaN` row:
```python
df_calendar = df_calendar.dropna(subset=["date"]).astype(str)
# → 72 unique dates
```

`TrafficMeasurements` build does **not** drop it — the row is converted to
`'nan'` (string) via `astype(str)` and uploaded. The inner join in
`v_measurements_enriched` silently filters out those orphan rows, but the
discrepancy makes the "results identical to original CSV" claim in T2.6
need a caveat.

Pick one of:
- **Preferred**: keep all 73 dates in `Calendar` (drop the `dropna` call).
  Confirm the NaN row is dropped at source or excluded by the original
  pipeline too so nothing fakely shows up.
- **Alternative**: also drop the NaN-date rows from `TrafficMeasurements`
  before upload.

Either keeps Calendar and TrafficMeasurements consistent.

---

## 2. After upstream fixes — closing T2.4 (Owner D)

1. Open [notebooks/create-views-DBrepo-notebook.ipynb](../notebooks/create-views-DBrepo-notebook.ipynb).
2. Run cell-by-cell. The first non-import cell prompts for DBRepo password.
3. Check the **"Discover the tables' internal names"** cell — confirm
   `TrafficMeasurements`, `Calendar`, `TrafficSites` map to the expected
   internal names. If the keys don't match exactly (e.g. DBRepo registered
   a different display name), adjust the dictionary lookups before
   continuing.
4. Run the three `client.create_view(...)` cells. Each should return a
   `ViewBrief` without raising.
5. Run the verification cells:
   - `v_measurements_enriched` count should be close to
     `TrafficMeasurements` row count (slightly fewer if the inner join
     excludes orphan rows; should match exactly once fix 1.2 is applied).
   - `v_weekday_measurements` sample should contain only Monday–Friday.
   - `v_peak_hour_measurements` sample should contain only rows with
     `start_time` in `[07:00:00–09:00:00]` or `[17:00:00–19:00:00]`.
6. If anything fails:
   - "column not found": probably the internal table name lookup —
     re-check the dict printed in cell 2 and the column references.
   - "operator not found": the filter operator string (`!=`, `>=`,
     `<=`) isn't in the MariaDB image's operator list. Try `<>` instead
     of `!=`. Print `image.operators` from a scratch cell to see what's
     supported:
     ```python
     img = client.get_image(database.container.image.id)
     print([op.value for op in img.operators])
     ```
7. Stage and commit when satisfied. (Don't push — user pushes manually.)

---

## 3. Notes for T2.6 (Owner D, next branch)

Things to remember when implementing the API-based experiment pipeline:

- **Column types come back as text.** DBRepo stored `date_id`, `start_time`,
  `end_time`, `day_of_week`, `site_id` as `text` because the upload
  notebook passed dataframes without explicit types. After
  `client.get_view_data(...)`, cast before doing arithmetic:
  ```python
  df["date_id"]    = pd.to_datetime(df["date_id"]).dt.date
  df["start_time"] = pd.to_timedelta(df["start_time"])
  # then HOUR equivalent:  df["start_time"].dt.components.hours
  ```
- **One data source view is enough for the experiment.** The original
  pipeline reads all rows and bins per-site. Pull from
  `v_measurements_enriched`; do not pre-filter via the weekday/peak-hour
  views unless you're doing a deliberate ablation — the bins would change.
- **Pagination.** `get_view_data(size=1_000_000)` covers the full table
  in one call today, but DBRepo may apply a server-side limit. Verify
  with `get_view_data_count` first; if the returned DataFrame is shorter
  than the count, page through using `page` / `size`.
- **Auth method.** HTTP Basic via `username` + `password`; the SDK's
  `RestClient` adds the `Authorization` header. For the experiment
  notebook, read credentials from environment variables with `getpass`
  as a fallback so the notebook is re-runnable:
  ```python
  import os
  username = os.environ.get("DBREPO_USER") or input("Username: ")
  password = os.environ.get("DBREPO_PASS") or getpass("Password: ")
  ```
- **Error handling.** Wrap each REST call in try/except for the typed
  exceptions the SDK raises:
  - `dbrepo.api.exceptions.MalformedError` — bad payload
  - `dbrepo.api.exceptions.ForbiddenError` — auth/permission
  - `dbrepo.api.exceptions.NotExistsError` — view/table missing
  - `dbrepo.api.exceptions.ResponseCodeError` — unexpected HTTP code
  - generic `requests.exceptions.ConnectionError` / `Timeout`
  Log clearly and retry transient errors (connection/5xx) with backoff.
- **README documentation** required by T2.6:
  - Endpoint base URL: `https://test.dbrepo.tuwien.ac.at`
  - Endpoints used (e.g. `/api/v1/database/{id}/view/{view_id}/data`,
    `/api/v1/database/{id}/view/{view_id}/data/count`)
  - Auth method: HTTP Basic
  - Database id: `2de50b61-ac24-4484-8117-dc0fe9dc1b7c`
- **Identical-results verification.** After implementing, run both the
  original CSV pipeline and the new DBRepo pipeline with the same random
  seed; assert that predicted-class counts match and the final metrics
  (accuracy, per-class precision/recall) match within a small tolerance.
  Mention this in the final report.
