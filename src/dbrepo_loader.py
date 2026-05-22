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

_INT_COLUMNS = (
    "observation_id",
    "flow",
    "flow_pc",
    "cong",
    "cong_pc",
    "dsat",
    "dsat_pc",
)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise DBRepoConfigError(
            f"Required environment variable {name!r} is not set. " "See .env.example."
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
    _require_env("DBREPO_DATABASE_ID")

    if password is None:
        password = os.environ.get("DBREPO_PASSWORD")
    if not password:
        password = getpass(f"Enter password for {username}: ")

    try:
        client = RestClient(endpoint=endpoint, username=username, password=password)
        # whoami() in this SDK version is local-only (just echoes the username),
        # so we use get_databases() as the real connectivity + auth probe.
        client.get_databases()
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


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce DBRepo's text-typed columns back to their logical Python types."""
    for col in _INT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(
            df["date"], errors="coerce", utc=True
        ).dt.tz_localize(None)
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
                database_id=database_id,
                view_id=view_id,
                page=page,
                size=size,
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
    progress: bool = True,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch rows of a registered view as a typed pandas DataFrame.

    Returns column names in their view-native form (e.g. ``site_id``,
    ``day_of_week``, ``observation_id``). No renaming is performed.

    If ``limit`` is set, stops after at least ``limit`` rows have been
    fetched (and trims the result to exactly ``limit``). This avoids
    pulling the full view when only a sample is needed and lets callers
    work around server-side pagination limits on large views.
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

    target = total if limit is None else min(limit, total)

    # When a small limit is requested, fetch a single small page instead of
    # the configured page_size — avoids materializing 100K rows server-side
    # just to throw most away.
    effective_page_size = page_size if limit is None else min(page_size, target)

    if progress:
        suffix = "" if limit is None else f" (limit={limit})"
        print(
            f"  load_view({view_name!r}): {total} rows total{suffix}, "
            f"paging at size={effective_page_size}",
            flush=True,
        )

    frames = []
    page = 0
    fetched = 0
    while fetched < target:
        t0 = time.monotonic()
        chunk = _fetch_with_retry(
            client,
            database_id,
            view_meta.id,
            page=page,
            size=effective_page_size,
        )
        if chunk is None or len(chunk) == 0:
            break
        frames.append(chunk)
        fetched += len(chunk)
        if progress:
            print(
                f"    page {page}: +{len(chunk)} rows "
                f"({fetched}/{target}) in {time.monotonic() - t0:.1f}s",
                flush=True,
            )
        page += 1

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if limit is not None and len(df) > limit:
        df = df.head(limit).copy()
    return _coerce_dtypes(df)
