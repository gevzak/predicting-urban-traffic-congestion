# DBRepo API Reimplementation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the experiment's CSV-based data loading with DBRepo REST API loading, and provide a runnable parity check that proves the API-loaded data is identical to the CSV-loaded data.

**Architecture:** A single `src/dbrepo_loader.py` module owns transport, auth, and dtype coercion; both the notebook and a `src/compare_csv_vs_dbrepo.py` script consume it. The comparison script doubles as an integration test — it produces a five-step diagnostic report and a clear PASS/FAIL line with distinct exit codes for data drift vs infrastructure failures.

**Tech Stack:** Python 3.12, `dbrepo` SDK (1.13.x), `pandas`, `python-dotenv`. No new dependencies; this project already pins these.

**Source spec:** `docs/superpowers/specs/2026-05-22-dbrepo-api-reimpl-design.md`

**Note on commits:** The repo owner manages git themselves. This plan does **not** include `git commit` steps. Tasks are sized so that a natural commit boundary lands at the end of each task; the owner will commit when ready.

---

## File Structure

**New files:**
- `src/dbrepo_loader.py` — auth, view fetch, dtype coercion, typed exceptions.
- `src/compare_csv_vs_dbrepo.py` — runnable CSV vs DBRepo parity check.

**Modified files:**
- `notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb` — replace CSV load with `load_view(...)`; rename column references; delete the feather-cache cell.
- `README.md` — append a "DBRepo API access" section after the existing "Views" section.
- `.env.example` — document the optional `DBREPO_PASSWORD` env var.

**Untouched:**
- `src/views_verification.py`.
- All feature engineering, train/val/test split, and MLP code in the notebook.

---

### Task 1: Loader — exception types and `make_client()`

**Files:**
- Create: `src/dbrepo_loader.py`

- [ ] **Step 1: Create the loader module with exceptions, env helpers, and `make_client()`**

Create `src/dbrepo_loader.py` with the following content:

```python
"""DBRepo REST API loader.

Owns all transport with the DBRepo instance defined in the repo-root ``.env``.
Exposes a small set of typed exceptions so callers can translate failures
into clear diagnostics without inspecting SDK exception strings.
"""
from __future__ import annotations

import os
import time
from getpass import getpass
from pathlib import Path
from typing import Optional

import pandas as pd
from dbrepo.RestClient import RestClient
from dotenv import load_dotenv


class DBRepoConfigError(RuntimeError):
    """A required environment variable is missing or empty."""


class DBRepoAuthError(RuntimeError):
    """Authentication failed (HTTP 401)."""


class DBRepoConnectionError(RuntimeError):
    """Could not reach the DBRepo endpoint (network / DNS / timeout)."""


class DBRepoViewNotFound(RuntimeError):
    """The requested view is not registered in the database."""


_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Integer columns in the v_*_measurements views. DBRepo returns these as text;
# coerce them back to nullable Int64 so downstream code sees real integers.
_INT_COLUMNS = (
    "observation_id",
    "flow", "flow_pc",
    "cong", "cong_pc",
    "dsat", "dsat_pc",
)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise DBRepoConfigError(
            f"Required environment variable {name!r} is not set. "
            "See .env.example."
        )
    return value


def make_client(password: Optional[str] = None) -> RestClient:
    """Authenticate against the DBRepo instance pointed to by ``.env``.

    Password resolution order: explicit ``password`` arg →
    ``DBREPO_PASSWORD`` env var → interactive ``getpass()`` prompt.
    """
    load_dotenv(_ENV_PATH)
    endpoint = _require_env("DBREPO_ENDPOINT")
    username = _require_env("DBREPO_USERNAME")
    _require_env("DBREPO_DATABASE_ID")  # validated up-front for clear errors

    if password is None:
        password = os.environ.get("DBREPO_PASSWORD")
    if not password:
        password = getpass(f"Enter password for {username}: ")

    try:
        client = RestClient(endpoint=endpoint, username=username, password=password)
        client.whoami()
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            raise DBRepoAuthError(
                f"Authentication failed for user {username!r}. "
                "Check DBREPO_USERNAME and the password."
            ) from exc
        raise DBRepoConnectionError(
            f"Could not reach DBRepo at {endpoint!r}: {exc}"
        ) from exc
    return client
```

- [ ] **Step 2: Verify happy path — `make_client()` authenticates and returns a working client**

From the repo root:

```bash
python -c "from src.dbrepo_loader import make_client; c = make_client(); print('whoami:', c.whoami())"
```

Expected: prompt for the password (or read it from `DBREPO_PASSWORD`), then print `whoami: <your-username>`. No tracebacks.

- [ ] **Step 3: Verify config-error path — missing env var raises `DBRepoConfigError`**

From the repo root:

```bash
DBREPO_USERNAME= python -c "
import os; os.environ.pop('DBREPO_USERNAME', None)
from src.dbrepo_loader import make_client, DBRepoConfigError
try:
    make_client()
    print('UNEXPECTED: no error')
except DBRepoConfigError as e:
    print('OK:', e)
"
```

Expected: prints `OK: Required environment variable 'DBREPO_USERNAME' is not set. See .env.example.`

- [ ] **Step 4: Verify connection-error path — bad endpoint raises `DBRepoConnectionError`**

```bash
DBREPO_ENDPOINT="https://nope.invalid.example" python -c "
from src.dbrepo_loader import make_client, DBRepoConnectionError
try:
    make_client(password='whatever')
    print('UNEXPECTED: no error')
except DBRepoConnectionError as e:
    print('OK:', e)
"
```

Expected: prints `OK: Could not reach DBRepo at 'https://nope.invalid.example': <SDK error text>`.

- [ ] **Step 5: Verify auth-error path — wrong password raises `DBRepoAuthError`**

```bash
DBREPO_PASSWORD="definitely-wrong-password" python -c "
from src.dbrepo_loader import make_client, DBRepoAuthError, DBRepoConnectionError
try:
    make_client()
    print('UNEXPECTED: no error')
except DBRepoAuthError as e:
    print('OK auth:', e)
except DBRepoConnectionError as e:
    print('FAIL: got connection error instead of auth error:', e)
"
```

Expected: prints `OK auth: Authentication failed for user '<your-username>'. Check DBREPO_USERNAME and the password.` If instead it prints `FAIL:`, the SDK's 401 response is not surfacing the substring `401` or `Unauthorized`; widen the heuristic in `make_client()` (e.g., also check for the substring `Forbidden` or the SDK's specific exception class name).

---

### Task 2: Loader — `_coerce_dtypes`, `_fetch_with_retry`, `load_view()`

**Files:**
- Modify: `src/dbrepo_loader.py` (append to the file from Task 1)

- [ ] **Step 1: Append the dtype-coercion helper, the 204-retry helper, and `load_view()`**

Append the following to `src/dbrepo_loader.py`:

```python
def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce DBRepo's text-typed columns back to their logical Python types."""
    for col in _INT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
    return df


def _fetch_with_retry(
    client: RestClient,
    database_id: str,
    view_id: str,
    page: int,
    size: int,
    *,
    retries: int = 10,
    delay: float = 5.0,
) -> pd.DataFrame:
    """Fetch a single page of view data, retrying on 204 (view warming up)."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return client.get_view_data(
                database_id=database_id, view_id=view_id,
                page=page, size=size,
            )
        except Exception as exc:
            last_exc = exc
            if "204" in str(exc) and attempt < retries - 1:
                time.sleep(delay)
                continue
            raise
    raise DBRepoConnectionError(
        f"View {view_id!r} did not return data after {retries * delay}s"
    ) from last_exc


def load_view(
    view_name: str,
    *,
    client: Optional[RestClient] = None,
    page_size: int = 100_000,
) -> pd.DataFrame:
    """Fetch every row of a registered view as a typed pandas DataFrame.

    Returns column names in their view-native form (e.g. ``site_id``,
    ``day_of_week``, ``observation_id``). No renaming is performed.
    """
    if client is None:
        client = make_client()

    load_dotenv(_ENV_PATH)
    database_id = _require_env("DBREPO_DATABASE_ID")

    try:
        views = client.get_views(database_id=database_id)
    except Exception as exc:
        raise DBRepoConnectionError(
            f"Could not list views on database {database_id!r}: {exc}"
        ) from exc

    view_meta = next((v for v in views if v.name == view_name), None)
    if view_meta is None:
        available = sorted(v.name for v in views)
        raise DBRepoViewNotFound(
            f"View {view_name!r} not registered. Available views: {available}"
        )

    total = client.get_view_data_count(database_id=database_id, view_id=view_meta.id)
    if total == 0:
        return pd.DataFrame()

    frames = []
    page = 0
    fetched = 0
    while fetched < total:
        chunk = _fetch_with_retry(
            client, database_id, view_meta.id,
            page=page, size=page_size,
        )
        if chunk is None or len(chunk) == 0:
            break
        frames.append(chunk)
        fetched += len(chunk)
        page += 1

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _coerce_dtypes(df)
```

- [ ] **Step 2: Verify `_coerce_dtypes` offline (no network)**

```bash
python -c "
import pandas as pd
from src.dbrepo_loader import _coerce_dtypes
df = pd.DataFrame({
    'observation_id': ['1', '2', '3'],
    'flow': ['10', '20', None],
    'date': ['2022-01-15', '2022-01-16', '2022-01-17'],
    'site_id': ['A', 'B', 'C'],
})
out = _coerce_dtypes(df)
print(out.dtypes)
print(out)
"
```

Expected output: `observation_id` and `flow` show dtype `Int64`, `date` shows `datetime64[ns]`, `site_id` stays `object`. The third `flow` value renders as `<NA>`.

- [ ] **Step 3: Verify `load_view()` happy path — fetches the experiment view**

```bash
python -c "
from src.dbrepo_loader import load_view
df = load_view('v_measurements_enriched')
print('shape:', df.shape)
print('columns:', list(df.columns))
print('dtypes:')
print(df.dtypes)
print('head:')
print(df.head(3))
"
```

Expected: non-empty shape (thousands of rows × 12 columns), columns match the view definition (`observation_id, site_id, date, day_of_week, start_time, end_time, flow, flow_pc, cong, cong_pc, dsat, dsat_pc`), integer columns show `Int64`, no tracebacks.

- [ ] **Step 4: Verify view-not-found path — raises `DBRepoViewNotFound`**

```bash
python -c "
from src.dbrepo_loader import load_view, DBRepoViewNotFound
try:
    load_view('v_does_not_exist')
    print('UNEXPECTED: no error')
except DBRepoViewNotFound as e:
    print('OK:', e)
"
```

Expected: `OK: View 'v_does_not_exist' not registered. Available views: ['v_measurements_enriched', 'v_weekday_measurements']` (the exact list depends on what is currently registered).

---

### Task 3: Comparison script

**Files:**
- Create: `src/compare_csv_vs_dbrepo.py`

- [ ] **Step 1: Create the comparison script**

Create `src/compare_csv_vs_dbrepo.py` with the following content:

```python
"""Parity check: original CSV source vs DBRepo view.

Prints a five-step diagnostic report and exits with:
  0 — full parity
  1 — any data mismatch (rows / schema / dtypes / NaNs / cell values)
  2 — infrastructure failure (connection, auth, config, missing view)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

# Make src/ importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbrepo_loader import (  # noqa: E402
    DBRepoAuthError,
    DBRepoConfigError,
    DBRepoConnectionError,
    DBRepoViewNotFound,
    load_view,
)


CSV_URL = (
    "https://data-sdublincoco.opendata.arcgis.com/api/download/v1/items/"
    "ce994c07d66e4ce582c4d608f339fcd9/csv?layers=0"
)
VIEW_NAME = "v_measurements_enriched"

RENAME_CSV_TO_VIEW = {
    "objectid": "observation_id",
    "site": "site_id",
    "day": "day_of_week",
}

INT_COLUMNS = (
    "observation_id",
    "flow", "flow_pc",
    "cong", "cong_pc",
    "dsat", "dsat_pc",
)

CANONICAL_ORDER = (
    "observation_id", "site_id", "date", "day_of_week",
    "start_time", "end_time",
    "flow", "flow_pc", "cong", "cong_pc", "dsat", "dsat_pc",
)


def load_csv() -> pd.DataFrame:
    return pd.read_csv(CSV_URL)


def load_dbrepo() -> pd.DataFrame:
    return load_view(VIEW_NAME)


def _normalize_time(series: pd.Series) -> pd.Series:
    """Coerce 'HH:MM[:SS]' / 'H:MM' / similar to canonical 'HH:MM' strings."""
    parsed = pd.to_datetime(series, format="mixed", errors="coerce")
    return parsed.dt.strftime("%H:%M")


def normalize(df_csv: pd.DataFrame, df_db: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Bring both DataFrames to a canonical schema + dtype + sort order.

    CSV columns are renamed to the view-native form; column-set intersection
    is kept (with anything dropped reported); dtypes for shared columns are
    coerced to one form on both sides; both frames are sorted by
    ``observation_id``.
    """
    df_csv = df_csv.rename(columns=RENAME_CSV_TO_VIEW)

    shared = [c for c in CANONICAL_ORDER if c in df_csv.columns and c in df_db.columns]
    csv_only = sorted(set(df_csv.columns) - set(df_db.columns))
    db_only = sorted(set(df_db.columns) - set(df_csv.columns))
    if csv_only:
        print(f"  dropping CSV-only columns: {csv_only}")
    if db_only:
        print(f"  dropping DBRepo-only columns: {db_only}")

    df_csv = df_csv[shared].copy()
    df_db = df_db[shared].copy()

    for col in INT_COLUMNS:
        if col in shared:
            df_csv[col] = pd.to_numeric(df_csv[col], errors="coerce").astype("Int64")
            df_db[col]  = pd.to_numeric(df_db[col],  errors="coerce").astype("Int64")
    if "date" in shared:
        df_csv["date"] = pd.to_datetime(df_csv["date"], errors="coerce", utc=True).dt.tz_localize(None)
        df_db["date"]  = pd.to_datetime(df_db["date"],  errors="coerce", utc=True).dt.tz_localize(None)
    for col in ("start_time", "end_time"):
        if col in shared:
            df_csv[col] = _normalize_time(df_csv[col])
            df_db[col]  = _normalize_time(df_db[col])

    df_csv = df_csv.sort_values("observation_id").reset_index(drop=True)
    df_db  = df_db.sort_values("observation_id").reset_index(drop=True)
    return df_csv, df_db


def report(
    df_csv: pd.DataFrame,
    df_db: pd.DataFrame,
    *,
    limit: Optional[int],
    dump_diff: Optional[Path],
) -> int:
    if limit is not None:
        df_csv = df_csv.head(limit)
        df_db = df_db.head(limit)

    first_failed: Optional[int] = None

    def fail_at(step: int) -> None:
        nonlocal first_failed
        if first_failed is None:
            first_failed = step

    # Step 1 — row counts
    n_csv, n_db = len(df_csv), len(df_db)
    match = n_csv == n_db
    print(f"[1/5] Row counts          CSV: {n_csv}   DBRepo: {n_db}   match: {match}")
    if not match:
        fail_at(1)

    # Step 2 — column sets
    cs_csv, cs_db = set(df_csv.columns), set(df_db.columns)
    csv_only = sorted(cs_csv - cs_db)
    db_only = sorted(cs_db - cs_csv)
    print(f"[2/5] Column sets         CSV-only: {csv_only}    DBRepo-only: {db_only}")
    if csv_only or db_only:
        fail_at(2)

    shared_cols = [c for c in df_csv.columns if c in df_db.columns]

    # Step 3 — dtypes
    print("[3/5] Dtypes per column")
    dtype_mismatch = False
    for col in shared_cols:
        c_d, d_d = str(df_csv[col].dtype), str(df_db[col].dtype)
        same = c_d == d_d
        print(f"        {col:<18} csv={c_d:<22} db={d_d:<22} match={same}")
        if not same:
            dtype_mismatch = True
    if dtype_mismatch:
        fail_at(3)

    # Step 4 — NaN counts
    print("[4/5] NaN counts")
    nan_mismatch = False
    for col in shared_cols:
        c_n = int(df_csv[col].isna().sum())
        d_n = int(df_db[col].isna().sum())
        delta = d_n - c_n
        print(f"        {col:<18} csv={c_n:<8} db={d_n:<8} delta={delta}")
        if delta != 0:
            nan_mismatch = True
    if nan_mismatch:
        fail_at(4)

    # Step 5 — cell-by-cell
    print("[5/5] Cell-by-cell")
    try:
        pd.testing.assert_frame_equal(df_csv, df_db, check_dtype=True, check_like=False)
        print("        identical")
    except AssertionError as exc:
        fail_at(5)
        print(f"        differs: {exc}")
        try:
            diff = df_csv.compare(df_db, keep_shape=False, keep_equal=False)
            print("        first 20 differing rows:")
            print(diff.head(20).to_string())
            if dump_diff is not None:
                diff.to_csv(dump_diff)
                print(f"        full diff written to {dump_diff}")
        except Exception as compare_exc:
            print(f"        could not compute df.compare(): {compare_exc}")

    suffix = f" (limit={limit})" if limit is not None else ""
    if first_failed is None:
        print(f"\nOVERALL: PASS{suffix}")
        return 0
    print(f"\nOVERALL: FAIL{suffix} — first mismatch at step {first_failed}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV vs DBRepo view parity check.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit both sides to the first N rows after sort.")
    parser.add_argument("--dump-diff", type=Path, default=None,
                        help="On mismatch, write the full df.compare() to this CSV path.")
    args = parser.parse_args()

    try:
        print("Loading CSV...")
        df_csv = load_csv()
        print("Loading DBRepo...")
        df_db = load_dbrepo()
    except (DBRepoConfigError, DBRepoAuthError,
            DBRepoConnectionError, DBRepoViewNotFound) as exc:
        print(f"DBRepo error: {exc}", file=sys.stderr)
        return 2

    df_csv, df_db = normalize(df_csv, df_db)
    return report(df_csv, df_db, limit=args.limit, dump_diff=args.dump_diff)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke run with `--limit` for fast feedback**

From the repo root:

```bash
python src/compare_csv_vs_dbrepo.py --limit 100
```

Expected: prints `Loading CSV...` then `Loading DBRepo...`, then the five `[k/5]` lines, then `OVERALL: PASS (limit=100)`. Exit code `0`.

If it prints `OVERALL: FAIL`, read the failing step's output and decide whether the mismatch is real (data drift) or a normalization gap (e.g., the canonical time format didn't catch some `start_time` formatting variant) — patch `normalize()` and re-run.

- [ ] **Step 3: Full parity run**

```bash
python src/compare_csv_vs_dbrepo.py
echo "exit: $?"
```

Expected: ends with `OVERALL: PASS` and `exit: 0`. This is the explicit equivalence claim.

- [ ] **Step 4: Verify infra-error path — exit code 2 on connection failure**

```bash
DBREPO_ENDPOINT="https://nope.invalid.example" python src/compare_csv_vs_dbrepo.py --limit 10
echo "exit: $?"
```

Expected: prints `DBRepo error: Could not reach DBRepo at 'https://nope.invalid.example': ...` to stderr, then `exit: 2`. Confirms infrastructure failures are distinguishable from data mismatches.

---

### Task 4: Notebook rewrite

**Files:**
- Modify: `notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb`

The notebook lives in `notebooks/`, the loader in `src/`. The notebook must add the repo root to `sys.path` and then `from src.dbrepo_loader import load_view`.

- [ ] **Step 1: Replace the CSV load cell**

Find the cell containing:

```python
# URL of the CSV data
csv_url = "https://data-sdublincoco.opendata.arcgis.com/api/download/v1/items/ce994c07d66e4ce582c4d608f339fcd9/csv?layers=0"

# Load the CSV data into a pandas DataFrame
df_traffic_flow = pd.read_csv(csv_url)

# Display the first few rows of the DataFrame and its information
print(df_traffic_flow.head())
print(df_traffic_flow.info())
```

Replace it with:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))

from src.dbrepo_loader import load_view

df_traffic_flow = load_view("v_measurements_enriched")

print(df_traffic_flow.head())
print(df_traffic_flow.info())
```

- [ ] **Step 2: Delete the feather cache cell**

Delete the cell containing:

```python
import pyarrow.feather as feather
feather.write_feather(df_traffic_flow, '/content/traffic_flow_data.feather')
```

This cell wrote a local cache file (forbidden — the experiment must read only from the API) and was unused downstream.

- [ ] **Step 3: Update the leading markdown cell to point at the API**

Replace the first markdown cell (currently links to the CSV on data.europa.eu) with:

```markdown
Source data is loaded from the project's DBRepo instance via the REST API,
through `src.dbrepo_loader.load_view`. The experiment uses the
`v_measurements_enriched` view, which is the de-normalised join of
`TrafficMeasurements`, `Calendar`, and `TrafficSites` covering January–June
2022 traffic flow measurements from South Dublin County Council (SDCC).

See `README.md` ("DBRepo API access") for endpoint, auth, and parity-check
documentation.
```

- [ ] **Step 4: Rename `'site'` references to `'site_id'`**

Update each of these cells (search the notebook for `'site'` in code):

```python
# was: print(f"Unique Sites: {df_traffic_flow['site'].nunique()}")
print(f"Unique Sites: {df_traffic_flow['site_id'].nunique()}")
print(f"Count per site: \n {df_traffic_flow['site_id'].value_counts()}")
```

```python
# was: sns.countplot(data=df_traffic_flow, x='site', order=df_traffic_flow['site'].value_counts().index)
sns.countplot(data=df_traffic_flow, x='site_id',
              order=df_traffic_flow['site_id'].value_counts().index)
```

```python
# was: df_traffic_flow.groupby('site')['cong'].head()
df_traffic_flow.groupby('site_id')['cong'].head()
```

```python
# was: df_traffic_flow.groupby('site')['cong'].transform(classify_congestion)
df_traffic_flow['target'] = (
    df_traffic_flow
    .groupby('site_id')['cong']
    .transform(classify_congestion)
)
```

```python
# was: site_class_dist = df_traffic_flow.groupby('site')['target'] ...
site_class_dist = (
    df_traffic_flow
    .groupby('site_id')['target']
    .value_counts(normalize=True)
    .unstack(fill_value=0)
)
```

```python
# was: top_sites = df_traffic_flow['site'].value_counts().head(10).index
top_sites = df_traffic_flow['site_id'].value_counts().head(10).index
```

```python
# was: sns.boxplot(data=df_traffic_flow[df_traffic_flow['site'].isin(top_sites)], x='site', y='cong')
sns.boxplot(
    data=df_traffic_flow[df_traffic_flow['site_id'].isin(top_sites)],
    x='site_id',
    y='cong',
)
```

- [ ] **Step 5: Rename the `'day'` reference to `'day_of_week'`**

Find the cell:

```python
# was:
day_map = {'MO':0, 'TU':1, 'WE':2, 'TH':3, 'FR':4, 'SA':5, 'SU':6}
df_traffic_flow['day_num'] = df_traffic_flow['day'].map(day_map)
```

Update to:

```python
day_map = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}
df_traffic_flow['day_num'] = df_traffic_flow['day_of_week'].map(day_map)
```

The `day_map` keys are unchanged — the view stores 2-letter codes (per `data/views.sql:68`'s `WHERE c.day_of_week NOT IN ('SA', 'SU')`).

- [ ] **Step 6: Final sanity scan for any leftover old column names**

From the repo root:

```bash
grep -n "'site'\|'day'\|'objectid'" notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb || echo "no leftover references"
```

Expected: prints `no leftover references`. If any line is printed, edit that cell to use the renamed column.

- [ ] **Step 7: Execute the notebook top-to-bottom and verify it runs without `KeyError`**

In a fresh kernel, run all cells. Expected: every cell that does not depend on `nvidia-smi` (Colab-only) executes without raising. The final MLP training cell trains and evaluates as before.

If a cell fails with `KeyError` on a column name, return to Step 6 and grep more broadly (e.g., `grep -n "site\b\|day\b\|objectid" ...`) — there is a missed reference.

---

### Task 5: README and `.env.example`

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Append a "DBRepo API access" section to `README.md`**

Append to the end of `README.md`:

```markdown

## DBRepo API access

The experiment loads data from the TU Wien DBRepo REST API only — no local
CSVs are read by the experiment notebook.

- **Base URL:** `https://test.dbrepo.tuwien.ac.at` (configurable via the
  `DBREPO_ENDPOINT` value in `.env`).
- **Client library:** `dbrepo` Python SDK (`RestClient`), which wraps the
  DBRepo REST API.
- **Endpoints used (through the SDK):**
  - `GET /api/user`                                 — whoami / auth check
  - `GET /api/database/{id}/view`                   — list views
  - `GET /api/database/{id}/view/{vid}/data`        — view rows (paged)
  - `GET /api/database/{id}/view/{vid}/data/count`  — view row count
- **Views consumed:** `v_measurements_enriched` (full experiment).
  `v_weekday_measurements` is available for weekday-only slices.
- **Authentication:** TU Wien DBRepo username + password.
  Username read from `DBREPO_USERNAME` in `.env`; password from the
  `DBREPO_PASSWORD` env var if set, otherwise prompted interactively via
  `getpass`. The `.env` file is in `.gitignore`.
- **Loader module:** `src/dbrepo_loader.py` (`load_view(name)` returns a
  typed `pandas.DataFrame` with view-native column names).
- **Parity check:** `python src/compare_csv_vs_dbrepo.py` verifies the
  DBRepo view returns the same data as the original CSV source. Exit codes:
  `0` = identical, `1` = data mismatch (see the printed 5-step report),
  `2` = infrastructure failure (connection, auth, config, missing view).
```

- [ ] **Step 2: Document `DBREPO_PASSWORD` in `.env.example`**

Append to `.env.example` (after the existing variables):

```
# Optional. If unset, scripts prompt interactively via getpass.
DBREPO_PASSWORD=
```

- [ ] **Step 3: Visual review**

Read both files. Check that:
- README's "DBRepo API access" section lists exactly the endpoints the loader actually hits (`whoami`, list views, view data, view data count).
- `.env.example` keeps its existing variables intact and only gains the new `DBREPO_PASSWORD` entry.

---

### Task 6: End-to-end verification

**Files:** (none modified — verification only)

- [ ] **Step 1: Final parity check from a clean shell**

From the repo root:

```bash
python src/compare_csv_vs_dbrepo.py
echo "exit: $?"
```

Expected: ends with `OVERALL: PASS` and `exit: 0`. Capture the output (or at least the final two lines) for the equivalence claim.

- [ ] **Step 2: Final notebook execution check**

In a fresh kernel, restart and run all cells in `notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb`. Expected: no `KeyError`, the load cell prints a non-empty DataFrame head, and the rest of the pipeline produces the same downstream artifacts (target distribution, train/val/test split sizes, MLP training history shape) as before.

- [ ] **Step 3: Confirm no local-file reads remain in the experiment notebook**

```bash
grep -nE "pd\.read_csv|read_feather|open\(['\"][^http]" notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb || echo "no local file reads"
```

Expected: prints `no local file reads`. The grep deliberately allows HTTP URLs (in case anything still references one for documentation only) but flags any `pd.read_csv` with a non-URL path or any `open()` call.

- [ ] **Step 4: Sign-off summary**

Confirm the four deliverables landed:
- `src/dbrepo_loader.py` exists and `python -c "from src.dbrepo_loader import make_client, load_view"` imports without error.
- `src/compare_csv_vs_dbrepo.py` runs end-to-end with exit 0.
- `notebooks/01_sdcc_traffic_full_pipeline_mlp.ipynb` runs top-to-bottom without `KeyError`.
- `README.md` has the "DBRepo API access" section and `.env.example` documents `DBREPO_PASSWORD`.
