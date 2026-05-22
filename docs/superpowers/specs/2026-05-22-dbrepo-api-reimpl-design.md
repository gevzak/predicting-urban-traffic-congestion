# DBRepo API Reimplementation — Design Spec

**Date:** 2026-05-22
**Status:** Draft, awaiting review

## Goal

Rewrite the experiment's data-loading code so it retrieves data exclusively from
the DBRepo REST API instead of the original CSV source. Provide a runnable
parity check that proves the API-loaded data is identical to the CSV-loaded
data on a row-by-row, cell-by-cell basis.

## Non-goals

- No changes to feature engineering, train/val/test splitting, or the MLP
  model code in the experiment notebook. Only the loading step changes, plus
  the mechanical column-name renames that follow from a different source
  schema.
- No re-running of training to compare model metrics. Data parity is the
  equivalence claim; model parity follows trivially.
- No refactor of `src/views_verification.py` beyond, optionally, a one-line
  switch to share `make_client()` with the new loader.

## File layout

```
src/
├── dbrepo_loader.py             [NEW]
├── compare_csv_vs_dbrepo.py     [NEW]
└── views_verification.py        [unchanged; optional one-line refactor]

notebooks/
└── 01_sdcc_traffic_full_pipeline_mlp.ipynb   [MODIFIED]

README.md                        [APPENDED: "DBRepo API access" section]
.env.example                     [MODIFIED: document optional DBREPO_PASSWORD]
```

## Component 1 — `src/dbrepo_loader.py`

The single point of contact with DBRepo. Both the notebook and the comparison
script consume it.

### Public surface

```python
def make_client(password: str | None = None) -> RestClient: ...
def load_view(view_name: str, *, client: RestClient | None = None) -> pd.DataFrame: ...

class DBRepoConfigError(RuntimeError): ...      # missing env var
class DBRepoAuthError(RuntimeError): ...        # 401
class DBRepoConnectionError(RuntimeError): ...  # transport / unreachable
class DBRepoViewNotFound(RuntimeError): ...     # view name not registered
```

### `make_client()`

1. Locate the repo-root `.env` via `Path(__file__).resolve().parent.parent / ".env"`
   so the loader works from any CWD (improvement over the relative `"../.env"`
   in `views_verification.py`).
2. Read `DBREPO_ENDPOINT`, `DBREPO_USERNAME`, `DBREPO_DATABASE_ID`. Missing any
   one → `DBRepoConfigError` naming the variable.
3. Password resolution order: explicit `password` arg → `DBREPO_PASSWORD` env
   var → `getpass()` prompt.
4. Construct `RestClient(endpoint, username, password)`.
5. Call `client.whoami()` once. Translate failures:
   - 401 / "Unauthorized" → `DBRepoAuthError` with hint to check
     `DBREPO_USERNAME` and the password.
   - connection refused / DNS / timeout → `DBRepoConnectionError` including
     the endpoint URL that was tried.
6. Return the authenticated client.

### `load_view(view_name)`

1. `client.get_views(database_id=...)`. Translate transport failures into
   `DBRepoConnectionError`.
2. Find the entry whose `.name == view_name`. If absent, raise
   `DBRepoViewNotFound` whose message lists the available view names.
3. Determine row count via `client.get_view_data_count(...)`.
4. Fetch rows with 204 retry (same pattern as
   `views_verification.fetch_view_data_with_retry`). If the row count exceeds
   one page (default `size=100_000`), loop `page=0..N`, concatenate.
5. Coerce dtypes for the `v_measurements_enriched` schema (and the other
   `v_*_measurements` views that share its columns):
   - Integer columns (`observation_id`, `flow`, `flow_pc`, `cong`, `cong_pc`,
     `dsat`, `dsat_pc`) → `Int64` (nullable, in case DBRepo returns NULL as
     text "None").
   - `date` → `datetime64[ns]`.
   - `start_time`, `end_time`, `site_id`, `day_of_week` → leave as `object`.
6. Return the DataFrame with view-native column names (no rename).

### Why this shape

One file owns transport + auth + dtype coercion. If DBRepo changes (text-vs-
int return type, new endpoint, additional warm-up state), there is exactly
one place to touch.

## Component 2 — `src/compare_csv_vs_dbrepo.py`

Runnable parity check.

### Shape

```python
def load_csv() -> pd.DataFrame: ...     # pd.read_csv(csv_url) per the original notebook
def load_dbrepo() -> pd.DataFrame: ...  # delegates to dbrepo_loader.load_view(...)
def normalize(df_csv, df_db) -> tuple[pd.DataFrame, pd.DataFrame]: ...
def report(df_csv, df_db, *, limit: int | None, dump_diff: Path | None) -> int: ...
def main() -> int: ...
if __name__ == "__main__": sys.exit(main())
```

### Alignment (`normalize`)

The two sources differ in column names and minor formatting. `normalize`
brings them to a single canonical form before any assertion runs.

1. Apply rename map to the CSV DataFrame only:
   `objectid → observation_id`, `site → site_id`, `day → day_of_week`. The
   DBRepo DataFrame is already in view-native form.
2. Compute the column-set diff. Drop columns that exist on only one side,
   printing what was dropped (silent drops are a debugging hazard).
3. Align column order to the view's column order.
4. Canonical dtype coercion on both sides for shared columns:
   - Integer columns → `Int64`.
   - `date` → `datetime64[ns]`.
   - `start_time`, `end_time` → string `"HH:MM"`. This is the most likely
     formatting drift between sources (CSV often returns `"7:00"`, DBRepo
     `"07:00:00"`); we normalize to one explicit form.
5. Sort both by `observation_id`, reset the index. Row order is not part of
   the equivalence claim.

### Diagnostic report

All five steps always run — the goal is one full picture per invocation, not
short-circuit on the first failure (the user explicitly wants debugging
affordances, not pass/fail-only output).

```
[1/5] Row counts          CSV: N    DBRepo: M    match? Y/N
[2/5] Column sets         diff (CSV-only): {...}    diff (DBRepo-only): {...}
[3/5] Dtypes per column   table (col, csv_dtype, dbrepo_dtype, match?)
[4/5] NaN counts          table (col, csv_nulls, dbrepo_nulls, delta)
[5/5] Cell-by-cell        pd.testing.assert_frame_equal(...)
                          on failure: pd.DataFrame.compare() → first 20
                          differing rows, with column

OVERALL: PASS   |   OVERALL: FAIL — see step N
```

### Flags

- `--limit N` — limit both sides to the first N rows after sort, for fast
  iteration on a slow network. PASS/FAIL line appends `(limit=N)` so a
  limited run is never confused with full parity.
- `--dump-diff PATH` — on mismatch, write the full `df.compare()` result to a
  CSV at `PATH`.

### Exit codes

- `0` — full parity.
- `1` — any data mismatch (rows, schema, dtypes, NaNs, or cell values).
- `2` — infrastructure failure (connection, auth, config, view missing).

A separate code for category 2 lets CI / a future Makefile target distinguish
"data drifted" from "DBRepo is down".

### Error handling at script level

Every `DBRepo*Error` raised by the loader is caught in `main()`, printed as a
one-line diagnostic identifying which env var or endpoint, and the script
exits with code 2. Stack traces only surface for unexpected exception types.

## Component 3 — Notebook rewrite

`notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb`:

1. Replace the CSV load cell:
   ```python
   import sys; sys.path.insert(0, "..")
   from src.dbrepo_loader import load_view
   df_traffic_flow = load_view("v_measurements_enriched")
   ```
2. Delete the `feather.write_feather(...)` cell — writing a local cache file
   contradicts the "no local CSV/file reads" requirement (and was never used
   downstream).
3. Mechanical column renames across the rest of the notebook:
   `df['site']` → `df['site_id']`, `df['day']` → `df['day_of_week']`,
   `df['objectid']` → `df['observation_id']`. Affects: groupby, value_counts,
   countplot, boxplot, and the `day_map` lookup site (not the map itself).
4. `day_map` keys are unchanged — the view stores 2-letter day codes
   (`MO`, `TU`, ...) per `data/views.sql:68`, matching the CSV.
5. Add a markdown cell at the top noting the source is the DBRepo view, with
   a pointer to `src/dbrepo_loader.load_view`.
6. Everything from the target-class construction onward is untouched.

## Component 4 — README and `.env.example`

### README — new section after "Views"

```markdown
## DBRepo API access

The experiment loads data from the TU Wien DBRepo REST API only.

- **Base URL:** `https://test.dbrepo.tuwien.ac.at` (configurable via `DBREPO_ENDPOINT`)
- **Client library:** `dbrepo` Python SDK (RestClient wrapper)
- **Endpoints used (via the SDK):**
  - `GET /api/user`                                — whoami / auth check
  - `GET /api/database/{id}/view`                  — list views
  - `GET /api/database/{id}/view/{vid}/data`       — view rows (paged)
  - `GET /api/database/{id}/view/{vid}/data/count` — view row count
- **Views consumed:** `v_measurements_enriched` (full experiment);
  `v_weekday_measurements` available for weekday-only slices.
- **Authentication:** TU Wien DBRepo username + password.
  Username from `DBREPO_USERNAME` in `.env`; password from `DBREPO_PASSWORD`
  if set, otherwise prompted via `getpass`.
- **Parity check:** `python src/compare_csv_vs_dbrepo.py` verifies the
  DBRepo view returns the same data as the original CSV source.
  Exit code 0 = identical.
```

### `.env.example`

Append:
```
# Optional. If unset, scripts prompt interactively via getpass.
DBREPO_PASSWORD=
```

## Error handling matrix

| Failure mode                  | Caught at        | Surfaced as              | Exit code |
| ----------------------------- | ---------------- | ------------------------ | --------- |
| Missing env var               | `make_client`    | `DBRepoConfigError`      | 2         |
| Bad endpoint / network        | `make_client` or `load_view` | `DBRepoConnectionError` | 2 |
| Bad creds / 401               | `make_client`    | `DBRepoAuthError`        | 2         |
| View not registered           | `load_view`      | `DBRepoViewNotFound`     | 2         |
| View warming up (204)         | `load_view`      | retried with backoff; raises only after N attempts | 2 |
| Row count / schema mismatch   | `compare` script | step 1/2 of report       | 1         |
| Dtype / NaN / cell mismatch   | `compare` script | step 3/4/5 of report     | 1         |

## Testing strategy

- `python src/compare_csv_vs_dbrepo.py` runs end-to-end and prints
  `OVERALL: PASS`. This is the explicit equivalence claim.
- The rewritten notebook executes top to bottom with no `KeyError` on any
  renamed column reference.
- Negative path on the loader: a deliberately wrong `DBREPO_ENDPOINT` value
  yields `DBRepoConnectionError` with a useful message; a wrong username
  yields `DBRepoAuthError`.

## Open questions

None at draft time.
