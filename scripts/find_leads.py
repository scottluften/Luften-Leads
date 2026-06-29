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

# CMS's public data has no free-text inspector narratives (e.g. literal
# mentions of "urine odor"), only tag-level categorization, so these two tags
# are the closest available proxies for an odor complaint:
# F584 - "safe, clean, comfortable, homelike environment" (broad environmental
#   catch-all; can also fire for unrelated issues like disrepair or lighting).
# F690 - incontinence/catheter care and UTI prevention; poor care here is a
#   direct, literal cause of urine odor, so it's a tighter signal than F584.
TARGET_TAGS = ["0584", "0690"]

# Whether a facility has actually addressed the citation yet. "No plan of
# correction" means the facility hasn't even committed to fixing it -- the
# hottest kind of lead. Higher rank means more urgent/unresolved.
STATUS_RANK = {
    "Deficient, Provider has no plan of correction": 3,
    "Deficient, Provider has plan of correction": 2,
    "Deficient, Provider has date of correction": 1,
    "Past Non-Compliance": 0,
    "No revisit needed": 0,
}

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX",
    "UT", "VT", "VA", "WA", "WV", "WI", "WY",
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
        state_count = 0
        for tag in TARGET_TAGS:
            rows = fetch_all(DEFICIENCIES_DATASET, [
                ("state", "=", state),
                ("deficiency_tag_number", "=", tag),
                # Complaint-triggered citations come from a specific resident/family
                # complaint, not a routine survey finding, which makes them the
                # closest available proxy for "odor complaint" without per-citation
                # narrative text.
                ("complaint_deficiency", "=", "Y"),
            ])
            state_count += len(rows)
            citations.extend(rows)
        print(f"  {state}: {state_count} complaint-driven citations")
    return citations


def fetch_providers():
    providers = {}
    for state in STATES:
        rows = fetch_all(PROVIDER_DATASET, [("state", "=", state)])
        for r in rows:
            providers[r["cms_certification_number_ccn"]] = r
    return providers


def build_leads(citations, providers):
    by_ccn = {}
    for c in citations:
        ccn = c["cms_certification_number_ccn"]
        if providers.get(ccn) is None:
            continue
        by_ccn.setdefault(ccn, []).append(c)

    leads = []
    for ccn, ccn_citations in by_ccn.items():
        provider = providers[ccn]
        # Multiple complaint-driven F584 citations at one facility is a stronger
        # signal than any single citation, so leads are one row per facility and
        # surface the most severe/recent citation, with the rest counted.
        c = max(
            ccn_citations,
            key=lambda c: (
                STATUS_RANK.get(c.get("deficiency_corrected", ""), 0),
                SEVERITY_RANK.get(c["scope_severity_code"], 0),
                c["survey_date"],
            ),
        )
        rank = SEVERITY_RANK.get(c["scope_severity_code"], 0)
        status_rank = STATUS_RANK.get(c.get("deficiency_corrected", ""), 0)
        # Stable across re-runs (same facility always hashes the same way),
        # used as the key for the "contacted" flag in the shared backend.
        lead_id = hashlib.sha1(ccn.encode()).hexdigest()[:12]
        # Facilities cited under both F584 and F690 have two independent
        # signals pointing at odor, which makes them a stronger lead.
        matched_tags = sorted({c["deficiency_tag_number"] for c in ccn_citations})
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
            "staffing_rating": provider.get("staffing_rating", ""),
            "nurse_staffing_hours_per_resident_day": provider.get(
                "reported_total_nurse_staffing_hours_per_resident_per_day", ""
            ),
            "nursing_staff_turnover_pct": provider.get("total_nursing_staff_turnover", ""),
            "survey_date": c["survey_date"],
            "scope_severity_code": c["scope_severity_code"],
            "severity_rank": rank,
            "status_rank": status_rank,
            "citation_status": c.get("deficiency_corrected", ""),
            "correction_date": c.get("correction_date", ""),
            "from_complaint": c.get("complaint_deficiency", ""),
            "infection_control_related": c.get("infection_control_inspection_deficiency", ""),
            "deficiency_description": c.get("deficiency_description", ""),
            "citation_count": len(ccn_citations),
            "matched_tags": ",".join(matched_tags),
            "propublica_search_url": f"{PROPUBLICA_SEARCH_URL}?search="
            + urllib.parse.quote(c["provider_name"]),
        })
    leads.sort(
        key=lambda l: (
            len(l["matched_tags"].split(",")),
            l["status_rank"],
            l["severity_rank"],
            l["survey_date"],
        ),
        reverse=True,
    )
    return leads


def save_csv(leads, path):
    fields = [
        "lead_id", "facility_name", "address", "city", "state", "zip_code",
        "phone", "ownership_type", "chain_name", "overall_rating",
        "health_inspection_rating", "staffing_rating",
        "nurse_staffing_hours_per_resident_day", "nursing_staff_turnover_pct",
        "survey_date", "scope_severity_code", "severity_rank", "status_rank",
        "citation_status", "correction_date",
        "from_complaint", "infection_control_related", "deficiency_description",
        "citation_count", "matched_tags", "propublica_search_url",
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
    print("Fetching F584/F690 (environment/incontinence care) citations...")
    citations = fetch_citations()
    print("Fetching facility contact/rating info...")
    providers = fetch_providers()
    leads = build_leads(citations, providers)
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    save_csv(leads, os.path.join(out_dir, "leads.csv"))
    save_json(leads, os.path.join(out_dir, "leads.json"))


if __name__ == "__main__":
    main()
