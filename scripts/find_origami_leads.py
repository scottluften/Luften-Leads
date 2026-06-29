import csv
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

ORIGAMI_BASE_URL = "https://origami.chat/api/v2"
ORIGAMI_API_KEY = os.environ.get("ORIGAMI_API_KEY")

# Single-region test run by default -- agent runs cost credits, so this
# validates output quality/contact-field completeness before scaling to
# all 50 states + DC. Accepts a free-text region description, not just a
# 2-letter state code (e.g. "New York City and the tri-state area (NY, NJ, CT)").
TEST_REGION = os.environ.get("ORIGAMI_TEST_REGION", "New York City and the tri-state area (NY, NJ, CT)")

# States the agent is actually asked to search -- used to flag rows it
# returned anyway from outside that scope (e.g. it once returned a TX
# facility for an NYC/tri-state run).
EXPECTED_STATES = set(
    os.environ.get("ORIGAMI_EXPECTED_STATES", "NY,NJ,CT").split(",")
)

TERMINAL_STATUSES = {
    "completed", "needs_input", "step_cap_hit", "incomplete",
    "cancelled", "errored", "timed_out",
}

PROMPT_TEMPLATE = """Find skilled nursing facilities in {region} with online evidence
(Google/Yelp reviews, local news coverage, or public complaints) of urine odor,
poor cleanliness, or incontinence/catheter care neglect. For each facility, return:
- facility_name
- address, city, state, zip_code
- administrator or facility manager contact name (if findable)
- contact email
- contact phone
- a short quote or summary of the evidence you found, with its source URL

Only include facilities where you found genuine evidence of an odor/cleanliness
complaint, not just any negative review. Aim for up to 25 facilities."""


def _headers():
    if not ORIGAMI_API_KEY:
        sys.exit("ORIGAMI_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {ORIGAMI_API_KEY}",
        "Content-Type": "application/json",
    }


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def get_credit_balance():
    resp = requests.get(f"{ORIGAMI_BASE_URL}/account/credits", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def start_agent_run(region):
    resp = requests.post(
        f"{ORIGAMI_BASE_URL}/agents",
        headers=_headers(),
        json={
            "name": f"Luften odor leads - {region}",
            "prompt": PROMPT_TEMPLATE.format(region=region),
            "model": "origami-lite",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["agent"]["id"], data["run"]["id"]


def poll_run(agent_id, run_id):
    url = f"{ORIGAMI_BASE_URL}/agents/{agent_id}/runs/{run_id}"
    while True:
        resp = requests.get(url, headers=_headers())
        resp.raise_for_status()
        run = resp.json()
        status = run.get("status")
        print(f"  run status: {status}")
        if status in TERMINAL_STATUSES:
            return run
        wait_s = int(resp.headers.get("Retry-After", 15))
        time.sleep(wait_s)


def fetch_table_rows(table_id):
    rows = []
    cursor = None
    while True:
        params = {"cells": "flat", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(
            f"{ORIGAMI_BASE_URL}/tables/{table_id}/rows",
            headers=_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("rows", data.get("data", []))
        rows.extend(batch)
        cursor = data.get("next_cursor") or data.get("nextCursor")
        if not cursor or not batch:
            break
    return rows


def normalize_key(name, zip_code):
    return (name or "").strip().lower(), (zip_code or "").strip()[:5]


def filter_and_flag(rows):
    kept = []
    dropped = 0
    out_of_region = 0
    for row in rows:
        odor = row.get("odor-evidence", {})
        if odor.get("is_genuine_complaint") is not True or not odor.get("evidence_quote"):
            dropped += 1
            continue
        state = (row.get("full-address", {}) or {}).get("state")
        row["out_of_region"] = bool(EXPECTED_STATES) and state not in EXPECTED_STATES
        if row["out_of_region"]:
            out_of_region += 1
        kept.append(row)
    print(f"Filtered: kept {len(kept)}, dropped {dropped} (not genuine/no quote), "
          f"{out_of_region} flagged out-of-region")
    return kept


def merge_with_existing(rows, existing_path):
    """Runs are per-region, so accumulate across runs instead of overwriting --
    each region query would otherwise wipe out every prior region's leads.
    Re-querying the same facility refreshes it with the newer data."""
    if not os.path.exists(existing_path):
        return rows
    with open(existing_path) as f:
        existing = json.load(f)
    by_key = {}
    for row in existing:
        addr = row.get("full-address", {}) or {}
        by_key[normalize_key(row.get("title"), addr.get("zip_code"))] = row
    for row in rows:
        addr = row.get("full-address", {}) or {}
        by_key[normalize_key(row.get("title"), addr.get("zip_code"))] = row
    return list(by_key.values())


def cross_check_overlap(origami_rows, cms_leads_path):
    if not os.path.exists(cms_leads_path):
        return origami_rows
    with open(cms_leads_path) as f:
        cms_leads = json.load(f)
    cms_keys = {
        normalize_key(l["facility_name"], l["zip_code"]) for l in cms_leads
    }
    for row in origami_rows:
        key = normalize_key(row.get("facility_name"), row.get("zip_code"))
        row["in_both_sources"] = key in cms_keys
    return origami_rows


def save_csv(rows, path):
    if not rows:
        return
    fields = sorted({key for row in rows for key in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} Origami leads to {path}")


def main():
    region = TEST_REGION

    balance_before = get_credit_balance()
    print(f"Credit balance before run: {balance_before}")

    print(f"Starting Origami agent run for {region}...")
    agent_id, run_id = start_agent_run(region)
    run = poll_run(agent_id, run_id)

    balance_after = get_credit_balance()
    print(f"Credit balance after run: {balance_after}")

    if run.get("status") != "completed":
        print(f"Run did not complete successfully: {run.get('status')}")
        print(json.dumps(run, indent=2)[:2000])
        return

    tables = run.get("response", {}).get("tables", [])
    if not tables:
        print("Run completed but produced no tables.")
        return

    table_id = tables[0]["id"]
    print(f"Fetching rows from table {table_id}...")
    rows = fetch_table_rows(table_id)
    rows = filter_and_flag(rows)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    cms_leads_path = os.path.join(out_dir, "leads.json")
    rows = cross_check_overlap(rows, cms_leads_path)

    slug = slugify(region)
    json_path = os.path.join(out_dir, f"origami_leads_{slug}.json")
    csv_path = os.path.join(out_dir, f"origami_leads_{slug}.csv")
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"Saved {len(rows)} Origami leads to {json_path}")
    save_csv(rows, csv_path)

    # Stable filenames, accumulated across runs (each run only covers one
    # region) so index.html and downstream users see every region queried
    # so far, not just the most recent one.
    latest_json_path = os.path.join(out_dir, "origami_leads.json")
    latest_csv_path = os.path.join(out_dir, "origami_leads.csv")
    merged = merge_with_existing(rows, latest_json_path)
    with open(latest_json_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Saved {len(merged)} Origami leads (accumulated) to {latest_json_path}")
    save_csv(merged, latest_csv_path)


if __name__ == "__main__":
    main()
