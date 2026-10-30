# M5 design: news ingestion (GDELT) and event clustering

Status: In progress (oct.30.2026) · Elephant: agent team · Branch `m5-news-ingestion`
Implements Structure Guide Decisions 3 (SQLite and FTS5 for text) and 8 (GDELT), and Build Plan M5.

## Problem

M6 will ask an LLM to read the news around a date and propose shocks. Before that, Warren needs the news itself: for each company and date, the articles that were public by then, tied to the right company, with ten copies of one story counted as one event. GDELT is free and global but machine-coded: duplicates, wrong company matches and tone that doesn't track importance are expected (Build Plan M5, learning notes). M5 builds the ingestion, the company matching, the clustering, and a measured precision.

**LLM use in M5:** none in the pipeline. One step uses LLM agents as labellers: they read titles and URLs in the precision sample and say whether each article is about the company (a text judgment, Decision 9). They never produce a number, a match or an event. How their labels are checked is under "Precision".

## Source and access

- **GDELT 2.0 Global Knowledge Graph (GKG 2.1), English stream, raw 15-minute files** from `data.gdeltproject.org/gdeltv2/` (`masterfilelist.txt` names every file with its size and MD5). Each row is one article: `GKGRECORDID`, `DATE` (UTC `YYYYMMDDHHMMSS`, when GDELT processed it, which is at or after publication), `SourceCommonName`, `DocumentIdentifier` (URL), `V2Themes`, `V2Organizations`, `V2Tone` (first value, average tone, is stored), and `Extras` with `<PAGE_TITLE>`. The translingual stream (`*.translation.gkg.csv.zip`) is skipped in Phase 1 and the report says so.
- **Decision 8** names GDELT (its Events and GKG tables) as the news source. M5 reads the GKG table only, because Events has no organisation list or page title. That is a choice within the decision, not a change to it; the Events table can be added later without a new decision.
- **Not BigQuery.** The Build Plan recommended it for history; it needs a billed Google Cloud project, a cost for the owner (CLAUDE.md). The raw files give the same rows for free. The Build Plan's M5 section now says so.
- **Not the DOC API** for the case library: it covers a rolling window of recent months, and every case date is in 2019–2025.
- **Licence** (Decision 11, guardrail 6): GDELT states its data is free and open for any use with attribution. Step 5 records the terms page and its date in the report.
- **Volume.** A 7-day window is 672 files. 24 cases, some overlapping, are about 15,000 files. Size per file isn't verified yet (the host is blocked here); Step 5 measures it and states total download and run time. Files are streamed one at a time: download, check MD5, match, store, drop the raw file. Nothing raw is committed.
- **Adapter** (Decision 11, guardrail 1): `domains/news/gdelt.py` is the only module that parses GDELT's format. It yields `ArticleRecord`s (url, source domain, seen_at, title, tone, themes, organisations, source file). Matching, clustering and queries never see a GDELT column. The manifest table is source-shaped (a file, its checksum) and is the adapter's own.
- **Network on oct.30.2026:** the cloud environment's proxy refuses `data.gdeltproject.org` and `api.gdeltproject.org` (403). Steps 0–4 need no network (fixtures). Step 5 needs the host allowed.

## The window and the point-in-time rule

- **Calendar:** the case calendar is New York time (`America/New_York`), a named setting (Decision 11, guardrail 3).
- **When an article counts as known:** a sighting's `seen_at` (GDELT `DATE`, UTC) is before `known_by(as_of)` = 24:00 New York time on the as-of date, converted to UTC (04:00 or 05:00 UTC next day). This matches the fundamentals rule, a fact counts if filed on or before the as-of date (`domains/fundamentals/facts.py:31`). `seen_at` is processing time, so the rule is conservative.
- **Window per case:** the 7 New York calendar days ending on the case date. The files fetched are every 15-minute file whose UTC timestamp falls in [00:00 New York on case date − 6, `known_by(case date)`), converted to UTC, so the early-morning UTC files of the next day are in.
- **Every query takes `as_of`:** `items_as_of` (each article as its earliest sighting known by the date), event runs (stored per as-of, read back by run) and `search(query, as_of)` (FTS5, one row per article) all filter sightings on `seen_at < known_by(as_of)`. Clustering runs only over those. A test ingests a story that continues after the date and checks that counts, titles and search results stop at the cut-off.

## Sightings, not first-come rows

GDELT lists one URL many times, sometimes with a different title. The store keeps **every sighting**: `article_sightings(article_id, seen_at, title, tone, themes, orgs, file_url)`, keyed by article and file. Under an as-of, an article is its **earliest sighting before the cut-off, with that sighting's own title and fields**. A later sighting can never lend its title to an earlier date, and the order in which windows were ingested doesn't change any answer (test: ingest two windows in both orders, same events).

## Company matching

- **Aliases are data** (Decision 11, guardrail 2): `domains/news/aliases.csv` with `ticker, alias, kind, from, note`, kind one of `include`, `subsidiary`, `exclude`. Seeded from `companies.aliases_json` (EDGAR name and former names) plus hand-added names. `subsidiary` rows name consolidated units whose news is the parent's news (Walmex for WMT, Janssen and LTL Management for JNJ, Activision Blizzard for MSFT from its 2023-10-13 close, Pioneer Natural Resources for XOM from its 2024-05-03 close), each with a `from` date; before it the row doesn't apply. `exclude` rows name different companies that share words: `apple daily`, `apple records`, `big apple`, `caterpillar fungus`, `coca-cola femsa`, `coca-cola europacific partners`, `coca-cola consolidated` (bottlers: separate listed companies, reported as `related` in the sample, not as matches).
- **Normalisation:** lowercase; `&` becomes ` and `; other punctuation becomes a space; trailing legal words *inc, corp, corporation, co, company, ltd, plc, et, al* (EDGAR writes "JOHNSON & JOHNSON ET AL") and a leading *the* dropped; spaces collapsed. So `p&g` is `p and g` and `j&j` is `j and j`. An alias shorter than 4 characters after normalisation is refused (test), which keeps `pg` and `ko` out.
- **Methods, per organisation string and per title:**
  1. `org_exact`: a GKG organisation, normalised, equals an include alias.
  2. `org_subsidiary`: it equals a subsidiary alias in force on the sighting's date.
  3. `title_alias`: no organisation matched, and the page title contains an include alias as a whole phrase, after every exclude phrase in the title has been masked (so "Apple Daily shuts down" doesn't match Apple).
  Exclusions act on the string they name, never on the article: a Coca-Cola article that also mentions Coca-Cola FEMSA still matches Coca-Cola. An article can match several companies (key: article, company; the strongest method is stored).
- **No made-up confidence.** `article_companies.method` is stored; precision per method comes from the labelled sample and is reported, never a fixed number written in code.
- **All companies on every pass.** Ingestion always matches every Phase 1 company, whatever window asked for the file, so overlapping windows (MSFT_2023-10-13 and XOM_2023-10-11) share files without losing rows.
- **Changing aliases re-fetches.** The manifest stores the SHA-256 of `aliases.csv` used for each file. `python -m domains.news rematch` re-fetches every file ingested under another alias hash and replaces that file's matches. Old matches from that file are deleted first (one transaction per file).

## Precision

- `python -m domains.news sample --seed N` draws, from the articles matched in the case windows, **50 per company for `org_exact`**, 25 for `org_subsidiary` and 25 for `title_alias` (all of them when fewer exist; the count is shown). Each draw is kept in `domains/news/match_sample.csv` with its seed; every draw is reported, including failed ones.
- **Labellers.** The data steward (Sonnet) labels every row `about`, `related` or `not`, with a one-line reason. The analyst (Opus, a different model, without seeing the first labels) labels a 40% subset drawn by seed. Code reports agreement as Cohen's kappa (Cohen 1960). Using LLMs as labellers is defensible only when validated (Gilardi, Alizadeh & Kubli 2023, *PNAS*); if kappa is below 0.6 the sample goes to the owner, as a decision card, before the gate is read.
- **Gate:** precision of `org_exact` (share labelled `about`) at least 0.80 per company, shown with its 95% Wilson interval (Wilson 1927; Brown, Cai & DasGupta 2001). A company below the gate gets alias fixes, `rematch`, and a new draw with a new seed. `title_alias` and `org_subsidiary` are kept only if they also reach 0.80.
- **Recall** is not measured (it needs every relevant article, which nobody has). The report says so.

## Clustering into events

- **Same article:** `article_id` = SHA-256 of the normalised URL (scheme and `www.` dropped, `utm_*`, `fbclid`, `ocid` and fragment removed).
- **Tokens:** regex `[a-z0-9]+` on the lowercased title, minus the stop words in `domains/news/stopwords.txt` (checked in) and the company's normalised alias words.
- **Themes:** the distinct theme names of a sighting (GKG's character offsets dropped), minus generic ones: names starting with any prefix in `GENERIC_THEME_PREFIXES` = `TAX_`, `WB_`, `GENERAL_`, `EPU_`, `USPEC_`, `CRISISLEX_`, `UNGP_`, `SOC_`, `MANMADE_`, `ECON_STOCKMARKET`. The list is a constant in `cluster.py` with a test.
- **Rule** (per company, over the articles known by `as_of`, ordered by `seen_at`, ties by `article_id`): an article joins the open event with the highest title similarity if it was seen within **48 hours** of that event's `last_seen` and either
  - title Jaccard with the event's tokens is at least **0.30**, or
  - title Jaccard is at least **0.15** and it shares at least **3** non-generic themes with the event's themes.
  Otherwise it starts a new event. Themes alone never join an article, so a busy week doesn't chain into one event. The event's tokens and themes are the union over its first five articles, so a long story doesn't drift.
- **An event records** `first_seen`, `last_seen`, `article_count`, `source_count` (distinct domains), its themes, median tone, and as label the title of the earliest article from the most-cited domain. `event_type` and `summary` stay NULL until M6.
- **Deterministic:** any input order gives the same events and ids (`event_id` = SHA-256 of cik, as_of and the event's first `article_id`, followed by the first 12 characters of the run id, so two runs on the same date with other parameters don't collide). Test with shuffled input.
- **Thresholds** (48 h, 0.30, 0.15, 3) are fixed before the real run. Step 5 reports from the hand-checked sample how many events are split or merged wrongly, and separately how many joins came from the theme branch. A change after that is a new version, with the reason written here. Literature: this is single-pass clustering from Topic Detection and Tracking (Allan, Papka & Lavrenko 1998; Yang, Pierce & Carbonell 1998), with Jaccard on word sets (Manning, Raghavan & Schütze 2008, ch. 19.6).

## Storage (migration `0009_news.sql`)

```sql
news_files(file_url TEXT PRIMARY KEY, file_ts TEXT, md5 TEXT, status TEXT,   -- ok | missing | bad_md5
           rows_total INTEGER, rows_kept INTEGER, aliases_sha256 TEXT, fetched_at TEXT)
articles(article_id TEXT PRIMARY KEY, url TEXT, source TEXT)
article_sightings(article_id TEXT REFERENCES articles, file_url TEXT REFERENCES news_files,
                  seen_at TEXT, title TEXT, tone REAL, themes_json TEXT, orgs_json TEXT,
                  PRIMARY KEY (article_id, file_url))
article_companies(article_id TEXT, file_url TEXT, cik TEXT, method TEXT,
                  PRIMARY KEY (article_id, file_url, cik))
event_runs(event_run_id TEXT PRIMARY KEY, cik TEXT, as_of TEXT, tz TEXT, params_json TEXT,
           input_sha256 TEXT, code_version TEXT, created_at TEXT)
events(event_id TEXT PRIMARY KEY, event_run_id TEXT REFERENCES event_runs, cik TEXT,
       first_seen TEXT, last_seen TEXT, article_count INTEGER, source_count INTEGER,
       label TEXT, themes_json TEXT, median_tone REAL, event_type TEXT NULL, summary TEXT NULL)
event_articles(event_id TEXT, article_id TEXT, PRIMARY KEY (event_id, article_id))
CREATE VIRTUAL TABLE sightings_fts USING fts5(title, content='article_sightings');  -- with sync triggers
```

- Times are UTC ISO 8601 with `Z`. No money in M5, so no currency column.
- **Coverage:** a file missing from the master list or failing its MD5 is a row with that status, never silently skipped. A row that can't be parsed is skipped and counted in `rows_bad`; it never drops the rest of the file. A file read before that can't be fetched again keeps its rows and stays due for `rematch`. The report shows expected vs fetched files per case window, and a window under 98% coverage is flagged.
- **Idempotent:** re-ingesting a window adds nothing (test).
- **Event runs reproduce.** `event_run_id` = SHA-256 of cik, as_of, the time zone, params (including the alias-set hash, because aliases decide which title words are dropped) and `input_sha256`, where `input_sha256` hashes the sorted list of (article_id, chosen sighting's file and `seen_at`) the run clustered. Running again on the same input returns the stored run. `rebuild-events` recomputes from stored sightings and checks the input hash first, then every event and membership; it exits 1 on any difference and names whether the input or the result changed.

## Article text

GDELT gives URLs, not text (Decision 8). Fetching publisher pages raises terms-of-use questions (Decision 11, guardrail 6) and many are paywalled or gone. M5 works on titles and GKG metadata; FTS5 indexes titles. Fetching text where allowed is a backlog item for M6 if extraction needs it.

## Commands

- `python -m domains.news ingest --case MSFT_2022-06-02 [--days 7]`, or `--all-cases` (also on `events`).
- `python -m domains.news rematch` (re-fetch files ingested under an older alias set).
- `python -m domains.news events --case MSFT_2022-06-02` (cluster as of the case date, store the run, print the events).
- `python -m domains.news rebuild-events EVENT_RUN_ID`.
- `python -m domains.news sample --seed N` and `python -m domains.news report` (coverage, precision with intervals and kappa, events per case; `data/reports/news/`).

## Steps

- **Step 0.** This design doc and its review; M5 "In progress" in the build plan.
- **Step 1.** `gdelt.py` adapter: parse a GKG 2.1 row into an `ArticleRecord`; master-list parsing, MD5 check, file list for a window; `known_by`. Tests on hand-written fixture rows in GKG's layout (`tests/news/fixtures/`): fields parsed, title from Extras, themes de-duplicated, a bad MD5 and a missing file recorded, the New York cut-off on both sides of midnight UTC in summer and winter, the window's file list includes the next UTC morning.
- **Step 2.** Migration 0009, `aliases.csv`, normalisation, matching, sightings, manifest, `rematch`. Tests: migration on an existing database; `apple daily` doesn't match Apple; a Coca-Cola article mentioning a bottler still matches Coca-Cola; a subsidiary before its `from` date doesn't match; short aliases refused; one article, two companies; overlapping windows share files; re-ingest adds nothing; a changed alias hash triggers re-fetch and replaces matches.
- **Step 3.** Clustering, event runs, `rebuild-events`, as-of search. Tests: ten outlets with near-identical titles are one event with `source_count` 10; two unrelated stories sharing themes on one day are two events; a story continuing after `as_of` stops there; earliest sighting's title is used; ingest order doesn't matter; shuffled input gives the same ids; rebuild matches and detects a changed input.
- **Step 4.** CLI, sample draws, precision with Wilson intervals, kappa, coverage and the report. Tests end to end on fixtures.
- **Step 5.** Real run (needs `data.gdeltproject.org`): first check the three field claims (DATE semantics, `PAGE_TITLE` present in 2019 files, `V2Organizations` format) on one real 2019 file and fix the fixtures if they differ; then ingest every case window, label, report coverage, precision and events per case in the build plan. M5 Done on merge.

Steps 0–4 merge as an engine-only PR, as M3 and M4 did; M5 stays In progress until Step 5.

## Exit criterion (Build Plan)

For every eval case date, the events around it are ingested, matched and clustered, with a hand-checked sample showing acceptable precision: `org_exact` at least 0.80 per company, labeller agreement kappa at least 0.6 (or the owner's labels), coverage reported per window.

## Alternatives considered

- **BigQuery.** Rejected for now: needs a billed Google Cloud project (a cost for the owner). Faster to filter; the same rows.
- **GDELT Events (CAMEO) table instead of GKG.** Not used: it codes actor-to-actor events from an article's first lines and has no organisation list or page title.
- **Embedding similarity for clustering.** Rejected for M5: needs a model or a paid API, and titles plus themes are enough for "ten copies of one story". `sqlite-vec` stays the Decision 3 future option.
- **Fetching full article text.** Deferred (terms of use, paywalls).
- **Matching on tickers in the text.** Rejected: GKG has no ticker field and `KO`, `PG`, `CAT` are common words.
- **Keeping the first sighting only.** Rejected in review: the stored date and title then depend on ingest order.

## Files

New: `domains/news/{gdelt,matching,cluster,store,report,__main__}.py`, `domains/news/{aliases.csv,stopwords.txt}`, `domains/news/match_sample.csv` (Step 5), `shared_kernel/migrations/0009_news.sql`, `tests/news/` with fixtures.
Changed: `docs/build-plan.md` (status, M5 source note, results), `README.md` (commands).

## Review log

- **PR review (oct.30.2026)**, gatekeeper NO-GO, then fixed: event runs didn't record the alias set (now in the params, rebuild names it); a parse error was recorded as a bad MD5 and one bad row dropped a file (now `rows_bad`, rows skipped); doc and README gaps (function names, legal words, events per case and the kappa floor in the report, `rematch`). Ideas taken: subsidiary dates in the case calendar, search one row per article, an explicit FTS key, a failed re-fetch keeps earlier rows, any request error recorded. To backlog: a migration test with rows in every older table.
- **Design review (oct.30.2026)**, explainer, analyst, professor in parallel.
  - *Accepted:* the doc said "no LLM" yet an LLM labels the sample (now stated, with a second labeller and kappa); the UTC-day window missed the next UTC morning; first-sighting-wins made dates and titles depend on ingest order (now every sighting is kept, earliest before the cut-off chosen); rows lost for good when aliases change or another company's window fetched the file first (all companies matched every pass, alias hash in the manifest, `rematch`); missing or bad files not recorded (status and coverage); exclusions read as article-level would drop Walmex and bottler mentions (now per string, Walmex a subsidiary); `p&g` normalised to `pg` (now `p and g`, short aliases refused); themes alone could chain a week into one event (title similarity now always required); rebuild wasn't reproducible from stored state (input hash); FTS search had no as-of (now `search(query, as_of)`); fixed confidences looked like probabilities (removed); sample of 25 too small (50, with Wilson intervals, every draw reported); unspecified tokeniser, stop words and theme list (written down); Build Plan still recommended BigQuery (note added).
  - *Rejected:* "Decision 8 names GDELT Events, so not using it drops a decision" (explainer). Decision 8 names GDELT as the source; reading one of its tables is within it, and nothing is dropped. No Structure Guide change.
  - *To backlog:* normalise `source_count` by GDELT's daily volume before M6 uses it as materiality (GDELT coverage grows over 2019–2025); a "why this matched / why these merged" trace per event for teaching; fetching article text where allowed; ExxonMobil Holdings alias after the 2026 reorganisation; the translingual stream for LatAm sources.

## Where the work stopped (oct.30.2026)

- Done on the branch: Steps 0–4 (adapter, migration 0009, aliases and matching, sightings and manifest, clustering and event runs, as-of search, sample draws, precision with Wilson intervals, kappa, coverage, CLI). Engine merged in PR #41.
- Next: Step 5, the real run. Blocked on oct.30.2026: the cloud environment refuses `data.gdeltproject.org` (403). Needs the host allowed in the environment's network settings, or a run from the owner's machine. Then check the three field claims on a real 2019 file before trusting the fixtures.
