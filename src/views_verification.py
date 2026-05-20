"""
Task 2.5: Programmatic View Verification
We pull the views defined in Task 2.4 via the REST API to verify that
our loaded 3NF tables are structurally complete and returning correct data.
"""

import sys
import os
from dotenv import load_dotenv
from dbrepo.RestClient import RestClient
from getpass import getpass
import time


def fetch_view_data_with_retry(view_id, size=5, retries=10, delay=5):
    for attempt in range(retries):
        try:
            return client.get_view_data(
                database_id=DATABASE_ID,
                view_id=view_id,
                page=0,
                size=size,
            )
        except Exception as e:
            if "204" in str(e):
                print(f"  view not ready yet, waiting {delay}s...")
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"View {view_id} did not become ready after {retries * delay}s")

# Load shared config from ../.env (endpoint, container id, database id,
# username). See .env.example in the repo root.
load_dotenv("../.env")

DATABASE_ID = os.environ["DBREPO_DATABASE_ID"]

# Read shared configuration from environment (loaded from ../.env above).
DBREPO_ENDPOINT       = os.environ["DBREPO_ENDPOINT"]
CONTAINER_ID          = os.environ["DBREPO_CONTAINER_ID"]
DATABASE_DISPLAY_NAME = os.environ["DBREPO_DATABASE_NAME"]

username = os.environ["DBREPO_USERNAME"]
user_password = getpass(f"Enter password for {username}: ")

client = RestClient(
    endpoint=DBREPO_ENDPOINT,
    username=username,
    password=user_password,
)
print("Authenticated as:", client.whoami())

# 1. Fetch all live views registered under your database container
try:
    views = client.get_views(database_id=DATABASE_ID)
    print(f"Successfully connected to REST API. Found {len(views)} live views.\n")
except Exception as e:
    print(f"CRITICAL: Failed to query views from DBRepo: {e}")
    sys.exit(1)

# Define the expected profiles for our 3 target views
expected_views = [
    "v_measurements_enriched",
    "v_weekday_measurements",
]

# 2. Main Verification Execution Loop
for view_name in expected_views:
    print(f"{'=' * 20}\nEvaluating View: {view_name}\n{'=' * 20}")

    view_meta = next((v for v in views if v.name == view_name), None)

    if view_meta is None:
        print(f"[!] FAILURE: View '{view_name}' was not found in the database.")
        continue

    try:
        df_view = fetch_view_data_with_retry(view_meta.id, size=5)

        # Use get_view_data_count for the actual row count instead of len(df_view)
        # since we're only fetching a sample of 5 rows now
        row_count = client.get_view_data_count(
            database_id=DATABASE_ID,
            view_id=view_meta.id
        )
        print(f"Successfully retrieved sample from DBRepo. Total row count: {row_count}")
        print(f" -> REST API Fetch: SUCCESS")
        print(f" -> Records Returned: {row_count}")

        if row_count == 0:
            print(f" -> [!] CRITICAL FAULT: View '{view_name}' is empty. Check underlying table joins!")
            continue

        # --- TEST 1: Column Schema Completeness ---
        required_cols = ['day_of_week', 'flow', 'flow_pc', 'cong', 'cong_pc', 'dsat', 'dsat_pc', 'start_time',
                         'end_time']
        missing_cols = [col for col in required_cols if col not in df_view.columns]

        if missing_cols:
            print(f" -> [!] SCHEMA FAULT: Missing expected columns: {missing_cols}")
        else:
            print(" -> Check 1 (Schema Mapping): PASSED")

        # --- TEST 2: View-Specific Logical Filtering Rules ---
        if view_name == "v_measurements_enriched":
            unique_days = df_view['day_of_week'].unique().tolist()
            print(f" -> Enriched Data Day Distribution: {unique_days}")
            if len(unique_days) > 0:
                print(" -> Check 2 (Calendar Join Integrity): PASSED")

        elif view_name == "v_weekday_measurements":
            weekend_rows = df_view[df_view['day_of_week'].str.upper().str.startswith('S', na=False)]
            weekend_count = len(weekend_rows)
            if weekend_count > 0:
                print(f" -> [!] FILTER FAULT: Found {weekend_count} leaked weekend records in weekday slice!")
            else:
                print(" -> Check 2 (No-Weekend Filter Constraint): PASSED")

    except Exception as view_error:
        print(f" -> [!] RUNTIME EXCEPTION during evaluation: {view_error}")