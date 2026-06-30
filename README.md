# Luften Leads

Internal sales-prospecting tool for Luften. Two lead sources, one interface — not public-facing.

## Two sources

### CMS (public data) — `scripts/find_leads.py`

Queries two public CMS datasets (no auth required):

- **Health Deficiencies** (`r5ix-sfxw`) — individual inspection citations per facility.
- **Provider Information** (`4pq5-n9py`) — facility contact/rating info (phone, address, ownership, star ratings).

Filters to complaint-driven citations (`complaint_deficiency = Y`) under two tags:

- **F584** — failure to provide a safe, clean, comfortable, homelike environment. Broad environmental catch-all; closest general-purpose proxy for odor/cleanliness complaints, but can also fire for unrelated issues (disrepair, lighting, temperature).
- **F690** — failure to provide appropriate incontinence/catheter care. Poor care here is a direct, literal cause of urine odor — a tighter signal than F584 on its own.

Dedupes to one row per facility (`citation_count > 1` means repeat citations — a stronger signal), ranks by: both codes cited first → correction status (uncorrected = most urgent) → CMS severity (A–L grid) → recency. Covers all 50 states + DC.

**Honest limitation:** CMS doesn't publish free-text inspector narratives, so F584+F690 are a structured proxy, not a literal "urine odor" search. Use the ProPublica link per row to verify the actual narrative before reaching out.

### Origami (AI-sourced) — `scripts/find_origami_leads.py`

Uses Origami's agent API to find leads that CMS structured data can't surface. Two use cases, one script:

- **Nursing homes** (`ORIGAMI_USE_CASE=nursing_home`, default) — searches reviews, local news, and public complaints for genuine odor/cleanliness evidence. Returns facility name, address, sourced evidence quote, and admin contact info (name, email, phone where findable).
- **Luxury high-rise** (`ORIGAMI_USE_CASE=high_rise`) — finds luxury residential high-rise buildings and their on-site property manager contact info (name, email, phone, management company).

Runs are **per-region** and **accumulate** — each run's results are merged into `output/origami_leads.json`/`.csv` rather than overwriting prior regions. Re-querying the same facility refreshes its entry. Each run also writes a point-in-time archive (`output/origami_leads_<region>.json`/`.csv`) and appends to a coverage manifest (`output/origami_runs.json`).

Requires an Origami API key (`og_live_*`) in a `.env` file or environment variable:

```
ORIGAMI_API_KEY=og_live_...
```

## Running

**CMS leads** (no credentials needed, re-run any time to refresh):
```
pip install requests
python scripts/find_leads.py
```

**Origami leads** (costs Origami credits — check balance first):
```
pip install requests python-dotenv
# Nursing home odor leads, NYC/tri-state (default):
python scripts/find_origami_leads.py

# Different region:
ORIGAMI_TEST_REGION="Chicago, IL" ORIGAMI_EXPECTED_STATES="IL,IN,WI" python scripts/find_origami_leads.py

# Luxury high-rise property managers, NYC:
ORIGAMI_USE_CASE=high_rise ORIGAMI_TEST_REGION="New York City" ORIGAMI_EXPECTED_STATES="NY" python scripts/find_origami_leads.py
```

## Output files

| File | Description |
|---|---|
| `output/leads.csv` | Full CMS leads — all fields, for manual analysis |
| `output/leads.json` | Slim CMS leads — only fields rendered by `index.html` |
| `output/cms_meta.json` | Date CMS data was last pulled + total row count |
| `output/origami_leads.json` | Accumulated Origami leads across all runs (web-facing) |
| `output/origami_leads.csv` | Same, as CSV |
| `output/origami_runs.json` | Coverage manifest — region, date, use_case, row count per run |
| `output/origami_leads_<region>.json/.csv` | Per-run archives |

## Interactive site (`index.html`)

Hosted on GitHub Pages. Two tabs:

**CMS tab** — searchable/sortable/filterable table of nursing home leads. Shows date data was last pulled from CMS. Filters: state, severity (A–L grid), citation code (F584/F690/both), correction status, contacted status.

**Origami tab** — leads from all Origami runs to date. Shows which regions have been queried and when. Filters: type (nursing home / high-rise), state, out-of-region flag, "also in CMS list" (facilities appearing in both sources — the strongest combined signal).

Both tabs share a "Mark contacted" button per row, backed by a Google Sheet + Apps Script so the flag is shared across team members.

### Apps Script setup (one-time)

1. Create a new Google Sheet. Rename one tab to `Contacted`. Add a header row: `lead_id | contacted | contacted_by | contacted_at | note`.
2. Go to **Extensions → Apps Script**. Paste in `apps-script/Code.gs`. Delete the default code first.
3. **Deploy → New deployment → Web app**. Execute as: Me. Who has access: Anyone. Deploy and authorize.
4. Copy the Web App URL. Paste it into the `const API_URL = ""` line in `index.html`.
5. Commit and push. Enable GitHub Pages in **Settings → Pages** (source: `main`, root).

Until step 4 is done, the page still works — "Mark contacted" just won't persist anywhere.
