# M5 design: news ingestion (GDELT) and event clustering

Status: In progress (oct.30.2026) · Elephant: agent team · Branch `m5-news-ingestion`
Implements Structure Guide Decisions 3 (SQLite and FTS5 for text) and 8 (GDELT), and Build Plan M5.

## Problem

M6 will ask an LLM to read the news around a date and propose shocks. Before that, Warren needs the news itself: for each company and date, the articles that were public by then, tied to the right company, with ten copies of one story counted as one event. GDELT is free and global but machine-coded: duplicates, wrong company matches and tone that doesn't track importance are expected (Build Plan M5, learning notes). M5 builds the ingestion, the company matching, the clustering, and a measured precision. No LLM is used in M5.

## Source and access

- **GDELT 2.0 Global Knowledge Graph (GKG 2.1), raw 15-minute files** from `data.gdeltproject.org/gdeltv2/` (the master file list `masterfilelist.txt` names every file with its size and MD5). Each row is one article: `GKGRECORDID`, `DATE` (UTC, `YYYYMMDDHHMMSS`, when GDELT saw it), `SourceCommonName` (domain), `DocumentIdentifier` (URL), `V2Themes`, `V2Organizations`, `V2Tone`, and `Extras` with `<PAGE_TITLE>`. Free and keyless.
- **Not BigQuery.** It needs a Google Cloud project and bills past the free tier; that is a cost for the owner to approve (CLAUDE.md). The raw files give the same rows.
- **Not the DOC API** for the case library: it searches a rolling window of recent months, and every case date is in 2019–2025.
- **Volume.** A 15-minute GKG file is a few MB zipped, so a 7-day window is about 670 files and a few GB. Files are streamed: download, check the MD5 against the master list, keep only rows that match a Phase 1 company, record the file in a manifest, and drop the raw file. Nothing raw is committed. A file already in the manifest is not fetched again.
- **Adapter** (Decision 11, guardrail 1): `domains/news/gdelt.py` is the only module that knows GDELT's format. It yields `ArticleRecord`s (url, source domain, published_at, title, tone, themes, organisations, source file). Matching, clustering and storage never see a GDELT column name, so a licensed news feed later is a new adapter.
- **Network on oct.30.2026:** the cloud environment's proxy refuses `data.gdeltproject.org` and `api.gdeltproject.org` (403). Steps 0–4 need no network (fixtures); Step 5 needs the host allowed.

## The window and the point-in-time rule

- **Window per case:** the 7 calendar days ending on the case date (case date − 6 … case date), configurable. A case date is the day the news became public (M3), so the event itself and the week of context before it are in.
- **When an article counts as known:** its GDELT `DATE` (UTC) is before the end of the case date in New York time (`America/New_York`, 24:00 local). The time zone is a named setting, never an implied one (Decision 11, guardrail 3). An article published at 23:00 New York time on the case date is in; one GDELT saw at 01:00 the next morning UTC but 21:00 New York time is also in. The rule is in one function, `known_by(as_of: date, tz) -> datetime`, with a test.
- **Every query takes `as_of`.** `articles_as_of` and `events_as_of` filter on `published_at < known_by(as_of)`. Clustering runs only over those articles, so an event's counts and its `last_seen` never include a later article (a test ingests a story that continues after the date and checks the count stops).

## Company matching

- **Aliases are data** (Decision 11, guardrail 2): `domains/news/aliases.csv` with `ticker, alias, kind` where kind is `include` or `exclude`. Seeded from `companies.aliases_json` (the EDGAR name and former names), normalised (lowercase, punctuation removed, legal suffixes *inc, corp, corporation, co, company, ltd, plc, the* dropped), plus hand-added common names (`exxon`, `exxonmobil`, `j&j`, `coca-cola`, `procter gamble`, `p&g`, `caterpillar`, `walmart`, `wal-mart`). Exclusions name known collisions: `apple daily`, `apple records`, `big apple`, `caterpillar fungus`, `coca-cola femsa`, `coca-cola europacific partners`, `coca-cola consolidated` (bottlers that are separate companies), `walmart de mexico` (Walmex, listed on its own).
- **Methods, in order:**
  1. `org_exact`: a normalised GKG organisation equals an include alias and no exclude alias. Confidence 0.9.
  2. `title_alias`: no organisation matched but the page title contains an include alias as a whole word. Confidence 0.6.
  An article can match more than one company (one row per company in `article_companies`).
- **Precision is measured, not assumed.** `python -m domains.news sample --seed 7 --n 25` draws 25 matched articles per company with a fixed seed into `domains/news/match_sample.csv`. The data steward labels each row `relevant` or `not` with a one-line reason, reading the title and URL (a text judgment, Decision 9; no number is produced). Code computes precision per company and method. **Acceptable:** at least 0.80 per company on `org_exact`. A company below that gets exclusion rules, and the sample is drawn again with a new seed (the old labels stay in the file, so a fix can't hide a failure). `title_alias` is reported and kept only if its precision is also 0.80 or above.
- **Recall** is not measured in M5 (it needs every relevant article, which nobody has). The report says so.

## Clustering into events

- **Same article, once.** `article_id` = SHA-256 of the normalised URL (scheme dropped, `www.` dropped, tracking parameters `utm_*`, `fbclid`, `ocid` removed). GDELT often lists a URL more than once; the first sighting wins.
- **Same story, one event** (per company, over the articles known by `as_of`, in time order, ties by `article_id`):
  - Title tokens: lowercase words, stop words and the company's own aliases removed.
  - An article joins the open event with the highest similarity if it was seen within **48 hours** of that event's `last_seen` and its title's Jaccard similarity with the event's token set is at least **0.30**, or the two share at least **3** of their GKG themes outside a list of generic themes (`TAX_FNCACT`, `WB_*` economics catch-alls, `GENERAL_*`). Otherwise it starts a new event.
  - The event's token set is the union of its first five titles, so a long-running story doesn't drift.
- **What an event records:** `first_seen`, `last_seen`, `article_count`, `source_count` (distinct source domains, the materiality signal for M6), the top themes, the median tone, and the title of the first article from the most-cited domain as its label. `event_type` and `summary` stay NULL until M6.
- **Deterministic:** the same articles in any input order give the same events and ids (`event_id` = SHA-256 of cik, as_of and the event's first `article_id`). A test shuffles the input.
- Thresholds (48 h, 0.30, 3 themes) are starting values, fixed before the real run. Step 5 reports how many events the hand-checked sample shows as split or merged wrongly; changing a threshold after that is a new version with the reason written here.

## Storage (migration `0009_news.sql`)

```sql
news_files(file_url TEXT PRIMARY KEY, file_ts TEXT, md5 TEXT, rows_total INTEGER,
           rows_kept INTEGER, fetched_at TEXT)                       -- the manifest
articles(article_id TEXT PRIMARY KEY, url TEXT, source TEXT, published_at TEXT, title TEXT,
         tone REAL, themes_json TEXT, orgs_json TEXT, text TEXT NULL, file_url TEXT REFERENCES news_files)
article_companies(article_id TEXT, cik TEXT, match_method TEXT, confidence REAL,
                  PRIMARY KEY (article_id, cik))
event_runs(event_run_id TEXT PRIMARY KEY, cik TEXT, as_of TEXT, tz TEXT, params_json TEXT,
           code_version TEXT, created_at TEXT)
events(event_id TEXT PRIMARY KEY, event_run_id TEXT REFERENCES event_runs, cik TEXT,
       first_seen TEXT, last_seen TEXT, article_count INTEGER, source_count INTEGER,
       label TEXT, themes_json TEXT, median_tone REAL, event_type TEXT NULL, summary TEXT NULL)
event_articles(event_id TEXT, article_id TEXT, PRIMARY KEY (event_id, article_id))
CREATE VIRTUAL TABLE articles_fts USING fts5(title, text, content='articles', content_rowid='rowid');
```

- `published_at` is stored in UTC ISO 8601 with the `Z`. Money is not stored in M5, so no currency column is needed.
- Ingestion is idempotent: `INSERT … ON CONFLICT DO NOTHING` on articles and matches; a re-run of the same window adds nothing (test).
- An event run stores its parameters and `as_of`, so `rebuild-events` clusters the same stored articles again and must give the same event ids (the news analogue of reproduce-to-the-cent).

## Article text

GDELT gives URLs, not text (Decision 8). Fetching thousands of publisher pages raises terms-of-use questions (Decision 11, guardrail 6) and many are paywalled or gone. M5 works on titles and GKG metadata only; `text` stays NULL and FTS5 indexes titles. Fetching text where a publisher allows it is a backlog item for M6 to pick up if extraction needs it.

## Commands

- `python -m domains.news ingest --case MSFT_2022-06-02 [--days 7]` or `--all-cases`, or `--ticker MSFT --from 2022-05-27 --to 2022-06-02`.
- `python -m domains.news events --case MSFT_2022-06-02` (cluster as of the case date, store the event run, print the events).
- `python -m domains.news rebuild-events EVENT_RUN_ID` (exits 1 on any difference).
- `python -m domains.news sample --seed 7 --n 25` and `python -m domains.news report` (precision per company and method, events per case, files fetched, rows kept; written to `data/reports/news/`).

## Steps

- **Step 0.** This design doc; M5 "In progress" in the build plan.
- **Step 1.** `gdelt.py` adapter: parse a GKG 2.1 row into an `ArticleRecord`; master list parsing and MD5 check; `known_by`. Tests on fixture rows checked into `tests/news/fixtures/` (written by hand in GKG's layout): fields parsed, title from Extras, a bad MD5 refused, the New York cut-off on both sides of midnight UTC, a file outside the window not requested.
- **Step 2.** Migration 0009, `aliases.csv`, normalisation and matching, storage and the manifest. Tests: the migration applies to an existing database; exclusions beat inclusions (`apple daily`); a bottler is not Coca-Cola; one article, two companies; re-ingesting a file adds nothing; URL normalisation.
- **Step 3.** Clustering and event runs. Tests: the same story from ten outlets (different URLs, near-identical titles) is one event with `source_count` 10; two unrelated stories on one day are two events; a story continuing after `as_of` stops at `as_of`; shuffled input gives the same ids; `rebuild-events` matches.
- **Step 4.** CLI, the sample command, precision computed from labels, and the report. Tests end to end on fixtures.
- **Step 5.** Real run (needs `data.gdeltproject.org`): ingest the window for every case in `cases.csv`, label the sample, report precision and events per case in the build plan. M5 Done on merge.

## Exit criterion (Build Plan)

For every eval case date, the events around it are ingested, matched and clustered, with a hand-checked sample showing acceptable precision (0.80 per company on `org_exact`, above).

## Alternatives considered

- **BigQuery.** Rejected for now: needs a billed Google Cloud project (a cost for the owner). Faster to filter; the same rows.
- **GDELT Events (CAMEO) table instead of GKG.** Rejected: it codes actor-to-actor events from the first lines of an article and has no organisation list or page title; company matching would be worse.
- **Embedding similarity for clustering.** Rejected for M5: needs a model or a paid API, and titles plus themes are enough for "ten copies of one story". `sqlite-vec` stays the Decision 3 future option.
- **Fetching full article text.** Deferred (terms of use, paywalls); see Article text.
- **Matching on tickers in the text.** Rejected: GKG has no ticker field and tickers like `KO`, `PG`, `CAT` are common words.

## Files

New: `domains/news/{gdelt,matching,cluster,store,report,__main__}.py`, `domains/news/aliases.csv`, `domains/news/match_sample.csv` (Step 5), `shared_kernel/migrations/0009_news.sql`, `tests/news/` with fixtures.
Changed: `docs/build-plan.md` (status, results), `README.md` (commands).

## Review log
