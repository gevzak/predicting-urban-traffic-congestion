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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbrepo_loader import (  # noqa: E402
    DBRepoAuthError,
    DBRepoConfigError,
    DBRepoConnectionError,
    DBRepoViewNotFound,
    load_view,
)


CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / \
    "Traffic_Flow_Data_Jan_to_June_2022_SDCC.csv"
VIEW_NAME = "v_measurements_enriched"

RENAME_CSV_TO_VIEW = {
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


def load_csv(limit: Optional[int] = None) -> pd.DataFrame:
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Local source CSV not found at {CSV_PATH}. "
            "This is the file that was uploaded to DBRepo per the upload "
            "notebook; it must exist for the parity check to be authoritative."
        )
    return pd.read_csv(CSV_PATH, nrows=limit)


def load_dbrepo(limit: Optional[int] = None) -> pd.DataFrame:
    return load_view(VIEW_NAME, limit=limit)


def _normalize_time(series: pd.Series) -> pd.Series:
    """Coerce 'HH:MM[:SS]' / 'H:MM' / '24:00' to canonical 'HH:MM' strings.

    '24:00' (midnight, used by SDCC for the end of the day) is mapped to
    '00:00' so pandas can parse it.
    """
    fixed = series.astype("string").str.replace("24:00", "00:00", regex=False)
    parsed = pd.to_datetime(fixed, format="mixed", errors="coerce")
    return parsed.dt.strftime("%H:%M")


def _csv_to_canonical(df_csv: pd.DataFrame) -> pd.DataFrame:
    """Apply the same transformations the upload notebook applied at ingest.

    Mirrors `notebooks/upload-data-DBrepo-notebook-v2.ipynb`:
      - drop the source CSV's ``ObjectId`` column (DBRepo generates its own
        ``observation_id`` 1..N from the CSV row order)
      - rename ``site`` → ``site_id``, ``day`` → ``day_of_week``
      - parse ``date`` as DD/MM/YYYY (the SDCC source format)
      - generate ``observation_id`` = 1..N matching the upload's enumeration
      - derive ``start_time`` from ``end_time`` − 15 minutes (the upload
        notebook drops the CSV's own ``start_time`` and re-derives it; we
        do the same so the comparison sees identical values on both sides)
    """
    df = df_csv.copy()
    df.columns = [c.strip() for c in df.columns]
    df = df.drop(columns=[c for c in df.columns if c.lower() == "objectid"])
    df = df.rename(columns={"site": "site_id", "day": "day_of_week"})
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")

    # Re-derive start_time the same way the upload notebook did.
    end_fixed = df["end_time"].astype("string").str.replace("24:00", "00:00", regex=False)
    df["start_time"] = (
        pd.to_datetime(end_fixed, format="%H:%M", errors="coerce")
        - pd.Timedelta(minutes=15)
    ).dt.strftime("%H:%M")

    df = df.reset_index(drop=True)
    df.insert(0, "observation_id", range(1, len(df) + 1))
    return df


def normalize(df_csv: pd.DataFrame, df_db: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Bring both DataFrames to a canonical schema + dtype + sort order."""
    df_csv = _csv_to_canonical(df_csv)

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
        df_csv["date"] = pd.to_datetime(df_csv["date"], errors="coerce")
        df_db["date"]  = pd.to_datetime(df_db["date"],  errors="coerce")
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

    n_csv, n_db = len(df_csv), len(df_db)
    match = n_csv == n_db
    print(f"[1/5] Row counts          CSV: {n_csv}   DBRepo: {n_db}   match: {match}")
    if not match:
        fail_at(1)

    cs_csv, cs_db = set(df_csv.columns), set(df_db.columns)
    csv_only = sorted(cs_csv - cs_db)
    db_only = sorted(cs_db - cs_csv)
    print(f"[2/5] Column sets         CSV-only: {csv_only}    DBRepo-only: {db_only}")
    if csv_only or db_only:
        fail_at(2)

    shared_cols = [c for c in df_csv.columns if c in df_db.columns]

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
        print(f"Loading CSV (limit={args.limit}) from {CSV_PATH}...")
        df_csv = load_csv(limit=args.limit)
        print(f"Loading DBRepo (limit={args.limit})...")
        df_db = load_dbrepo(limit=args.limit)
    except (DBRepoConfigError, DBRepoAuthError,
            DBRepoConnectionError, DBRepoViewNotFound) as exc:
        print(f"DBRepo error: {exc}", file=sys.stderr)
        return 2

    df_csv, df_db = normalize(df_csv, df_db)
    return report(df_csv, df_db, limit=args.limit, dump_diff=args.dump_diff)


if __name__ == "__main__":
    sys.exit(main())
