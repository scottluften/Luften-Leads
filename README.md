# Luften Leads

Internal sales-prospecting tool for Luften. Pulls real CMS nursing home inspection data and generates a ranked list of facilities likely to need odor/cleanliness remediation — not public-facing, just a script + a CSV.

## What it does

Queries two public CMS datasets (no auth required):

- **Health Deficiencies** (`r5ix-sfxw`) — individual inspection citations per facility.
- **Provider Information** (`4pq5-n9py`) — facility contact/rating info (phone, address, ownership, star ratings).

It filters citations to two CMS tags, restricted to citations flagged `complaint_deficiency = Y` (i.e. ones that came from an actual resident/family complaint rather than a routine survey finding):

- **F584** — "Honor the resident's right to a safe, clean, comfortable and homelike environment." A broad environmental catch-all; the closest general-purpose CMS tag to odor/cleanliness complaints, but can also fire for unrelated issues (disrepair, lighting, temperature, privacy).
- **F690** — "Provide appropriate care for residents who are continent or incontinent of bowel/bladder, appropriate catheter care, and appropriate care to prevent urinary tract infections." Poor incontinence/catheter care is a direct, literal cause of urine odor, making this a tighter signal than F584 on its own.

It joins in facility contact info, dedupes to **one row per facility** (a facility cited multiple times shows `citation_count > 1`), and ranks the result: facilities matching **both** F584 and F690 first, then by correction status (still-uncorrected citations rank above ones with a committed correction date), then citation severity (CMS's A–L scope/severity grid), then recency. Covers all 50 states + DC.

It also carries over each facility's **staffing data** from the same provider dataset (no extra API call needed) — `staffing_rating` (CMS's 1–5 star rating), nurse staffing hours/resident/day, and nursing staff turnover %. Understaffed facilities are more likely to have ongoing hygiene/incontinence-care lapses, so this is a free secondary signal you can sort/filter by, even though it's not part of the ranking formula.

**Honest limitation:** CMS's public data does not include free-text inspector narratives, so this isn't a literal "mentions urine odor" search — F584+F690 are the best structured proxy available. Some matching citations will still turn out to be about something else. Treat the output as a prioritized list to skim/verify (e.g. via the ProPublica link per row, which full-text searches the actual inspector narratives), not a guaranteed match.

## What's in the output

`output/leads.csv` — one row per facility, with:

- Facility name, address, city, state, zip
- Phone number (real, from CMS)
- Ownership type, chain name, overall/health-inspection star ratings
- Citation date, severity code, and correction status
- `matched_tags` — which of F584/F690 this facility was cited under (`0584`, `0690`, or both)
- `citation_count` — how many complaint-driven F584/F690 citations this facility has (repeat citations are a stronger signal)
- `status_rank` / `citation_status` — whether the facility has even committed to fixing it yet (3 = no plan of correction, the most urgent; 1 = has a correction date; 0 = resolved/past non-compliance)
- `staffing_rating`, `nurse_staffing_hours_per_resident_day`, `nursing_staff_turnover_pct` — CMS staffing data, a free secondary signal (understaffing correlates with hygiene lapses)
- `propublica_search_url` — a direct link to search ProPublica's Nursing Home Inspect for this facility's full inspection narrative text, to manually verify the odor language before reaching out

**Not included** (no public source exists): named administrator/manager, email address. Getting those would require manual lookup per facility or a paid contact-enrichment API (Apollo.io, ZoomInfo, Hunter.io) — a deliberate future decision, not wired up yet.

## Running it

```
pip install requests
python scripts/find_leads.py
```

No credentials needed — CMS's Provider Data Catalog API is public. Re-run any time to refresh; it overwrites `output/leads.csv`.

## States covered

All 50 states + DC. Edit the `STATES` list in `scripts/find_leads.py` to narrow this if you only want specific states.

## Interactive version (`index.html`)

A searchable/sortable/filterable table of the leads, with a "Mark contacted" button per row. Filterable by state, severity, and citation code (F584 only / F690 only / both). Meant to be hosted on **GitHub Pages** (free, no build step, doesn't touch Netlify credits).

Since GitHub Pages is static-only, the "contacted" flag needs somewhere shared to live so it's visible across people/devices. That's a **Google Sheet + Apps Script**, set up once:

1. Create a new Google Sheet. Rename one tab to `Contacted`. Add a header row: `lead_id | contacted | contacted_by | contacted_at | note`.
2. In the Sheet, go to **Extensions → Apps Script**. Delete the default code and paste in the contents of `apps-script/Code.gs` from this repo.
3. Click **Deploy → New deployment → type: Web app**. Set "Execute as: Me" and "Who has access: Anyone". Deploy, and authorize when prompted.
4. Copy the **Web app URL** it gives you.
5. Open `index.html` in this repo and paste that URL into the `const API_URL = "";` line near the top of the `<script>` block.
6. Commit and push. Enable GitHub Pages in this repo's **Settings → Pages** (source: `main` branch, root) if not already on.

Until step 5 is done, the page still works (table, search, filters) but "Mark contacted" won't be saved anywhere — it'll show a banner reminding you the API isn't configured.

Re-running `scripts/find_leads.py` regenerates `output/leads.json` with the same `lead_id` for unchanged citations, so contacted status survives a refresh.
