# Luften Leads

Internal sales-prospecting tool for Luften. Pulls real CMS nursing home inspection data and generates a ranked list of facilities likely to need odor/cleanliness remediation — not public-facing, just a script + a CSV.

## What it does

Queries two public CMS datasets (no auth required):

- **Health Deficiencies** (`r5ix-sfxw`) — individual inspection citations per facility.
- **Provider Information** (`4pq5-n9py`) — facility contact/rating info (phone, address, ownership, star ratings).

It filters citations to tag **F584** ("safe, clean, comfortable, homelike environment") — the closest structured CMS category to odor/cleanliness complaints — across Luften's current service states, joins in facility contact info, and ranks the result by citation severity (CMS's A–L scope/severity grid) then recency.

**Honest limitation:** CMS's public data does not include free-text inspector narratives, so this isn't a literal "mentions urine odor" search — it's the best structured proxy available. Some F584 citations will be about things other than odor (e.g. privacy, temperature). Treat the output as a prioritized list to skim, not a guaranteed match.

## What's in the output

`output/leads.csv` — one row per citation, with:

- Facility name, address, city, state, zip
- Phone number (real, from CMS)
- Ownership type, chain name, overall/health-inspection star ratings
- Citation date, severity code, and correction status

**Not included** (no public source exists): named administrator/manager, email address. Getting those would require manual lookup per facility or a paid contact-enrichment API (Apollo.io, ZoomInfo, Hunter.io) — a deliberate future decision, not wired up yet.

## Running it

```
pip install requests
python scripts/find_leads.py
```

No credentials needed — CMS's Provider Data Catalog API is public. Re-run any time to refresh; it overwrites `output/leads.csv`.

## Current service states

Local: `NY`, `NJ`, `PA`. Shipped: `GA`, `CO`, `CT`, `AR`, `IN`, `KS`, `NC`, `FL`. Edit the `STATES` list in `scripts/find_leads.py` to add/remove states as Luften's service area changes.
