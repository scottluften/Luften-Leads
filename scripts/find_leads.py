import csv
import hashlib
import json
import os
import urllib.parse
import requests

PROPUBLICA_SEARCH_URL = "https://projects.propublica.org/nursing-homes/findings/search"

DEFICIENCIES_DATASET = "r5ix-sfxw"
PROVIDER_DATASET = "4pq5-n9py"
BASE_URL = "https://data.cms.gov/provider-data/api/1/datastore/query"

# CMS scope/severity grid: A-C = no harm, D-F = no harm/potential for more
# than minimal, G-I = actual harm, J-L = immediate jeopardy. Higher rank
# means a more serious finding, which makes for a stronger sales lead.
SEVERITY_RANK = {
    **{c: 1 for c in "ABC"},
    **{c: 2 for c in "DEF"},
    **{c: 3 for c in "GHI"},
    **{c: 4 for c in "JKL"},
}

# F584 covers "safe, clean, comfortable, homelike environment" — the closest
# structured CMS tag to odor/cleanliness complaints. CMS's public data does
# not include free-text inspector narratives (e.g. literal mentions of
# "urine odor"), only this tag-level categorization.
TARGET_TAG = "0584"

STATES = [
    "NY", "NJ", "PA",  # local service area
    "GA", "CO", "CT", "AR", "IN", "KS", "NC", "FL",  # current shipped clients
]


def fetch_all(dataset_id, conditions, limit=500):
    results = []
    offset = 0
    while True:
        params = {"limit": limit, "offset": offset}
        for i, (prop, op, value) in enumerate(conditions):
            params[f"conditions[{i}][property]"] = prop
            params[f"conditions[{i}][operator]"] = op
            params[f"conditions[{i}][value]"] = value
        resp = requests.get(f"{BASE_URL}/{dataset_id}/0", params=params)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("results", [])
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return results


def fetch_citations():
    citations = []
    for state in STATES:
        rows = fetch_all(DEFICIENCIES_DATASET, [
            ("state", "=", state),
            ("deficiency_tag_number", "=", TARGET_TAG),
            # Complaint-triggered F584 citations come from a specific resident/family
            # complaint, not a routine survey finding -- for this F-tag, complaints
            # skew heavily toward odor/cleanliness issues rather than e.g. privacy or
            # temperature, which makes this the closest available proxy for "odor
            # complaint" without per-citation narrative text.
            ("complaint_deficiency", "=", "Y"),
        ])
        print(f"  {state}: {len(rows)} complaint-driven citations")
        citations.extend(rows)
    return citations


def fetch_providers():
    providers = {}
    for state in STATES:
        rows = fetch_all(PROVIDER_DATASET, [("state", "=", state)])
        for r in rows:
            providers[r["cms_certification_number_ccn"]] = r
    return providers


def build_leads(citations, providers):
    leads = []
    for c in citations:
        ccn = c["cms_certification_number_ccn"]
        provider = providers.get(ccn)
        if not provider:
            continue
        rank = SEVERITY_RANK.get(c["scope_severity_code"], 0)
        # Stable across re-runs (same citation always hashes the same way),
        # used as the key for the "contacted" flag in the shared backend.
        lead_id = hashlib.sha1(
            f"{ccn}|{c['survey_date']}|{c['deficiency_tag_number']}".encode()
        ).hexdigest()[:12]
        leads.append({
            "lead_id": lead_id,
            "facility_name": c["provider_name"],
            "address": c["provider_address"],
            "city": c["citytown"],
            "state": c["state"],
            "zip_code": c["zip_code"],
            "phone": provider.get("telephone_number", ""),
            "ownership_type": provider.get("ownership_type", ""),
            "chain_name": provider.get("chain_name", ""),
            "overall_rating": provider.get("overall_rating", ""),
            "health_inspection_rating": provider.get("health_inspection_rating", ""),
            "survey_date": c["survey_date"],
            "scope_severity_code": c["scope_severity_code"],
            "severity_rank": rank,
            "citation_status": c.get("deficiency_corrected", ""),
            "correction_date": c.get("correction_date", ""),
            "from_complaint": c.get("complaint_deficiency", ""),
            "infection_control_related": c.get("infection_control_inspection_deficiency", ""),
            "deficiency_description": c.get("deficiency_description", ""),
            "propublica_search_url": f"{PROPUBLICA_SEARCH_URL}?search="
            + urllib.parse.quote(c["provider_name"]),
        })
    leads.sort(key=lambda l: (l["severity_rank"], l["survey_date"]), reverse=True)
    return leads


def save_csv(leads, path):
    fields = [
        "lead_id", "facility_name", "address", "city", "state", "zip_code",
        "phone", "ownership_type", "chain_name", "overall_rating",
        "health_inspection_rating", "survey_date", "scope_severity_code",
        "severity_rank", "citation_status", "correction_date",
        "from_complaint", "infection_control_related", "deficiency_description",
        "propublica_search_url",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(leads)
    print(f"Saved {len(leads)} leads to {path}")


def save_json(leads, path):
    with open(path, "w") as f:
        json.dump(leads, f, indent=2)
    print(f"Saved {len(leads)} leads to {path}")


def main():
    print("Fetching F584 (unsafe/unclean environment) citations...")
    citations = fetch_citations()
    print("Fetching facility contact/rating info...")
    providers = fetch_providers()
    leads = build_leads(citations, providers)
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    save_csv(leads, os.path.join(out_dir, "leads.csv"))
    save_json(leads, os.path.join(out_dir, "leads.json"))


if __name__ == "__main__":
    main()
