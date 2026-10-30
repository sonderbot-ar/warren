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

## Field checks on real files (oct.30.2026, Step 5)

Read on real GKG files from 2019-04-23 to 2025-09-19 before any case window was ingested:

- **Download.** GDELT lists its files as `http://`; this environment allows only https, and `data.gdeltproject.org` serves the same paths over https. The adapter fetches over https; the manifest keeps the listed URL as the file's name.
- **`DATE`** is the 15-minute batch the article was processed in (20190423150000 for every row of that file); some rows also carry `<PAGE_PRECISEPUBTIMESTAMP>`, an earlier publication time. Warren keeps the batch time: later, so conservative for as-of.
- **`V2Organizations`** is `Name,offset;Name,offset` with the publisher's capitals ("Microsoft,3701"); the normaliser lowercases, as designed. Every row has 27 columns.
- **`PAGE_TITLE`** is missing from every row until about October 2019 (none on 2019-04-23, 2019-07-19, 2019-08-26 or 2019-09-20; every row on 2019-10-23 and in each later year checked). Six case windows fall before it. Without titles every article would be its own event, so a sighting with no page title takes its headline words from the URL's last path part (`/microsoft-cuts-revenue-forecast-123.html` → "microsoft cuts revenue forecast", when at least three words), flagged `title_from_url` (migration 0010). Those words cluster but never match a company on their own: `title_alias` reads page titles only. The coverage table in the report counts, per case window, the sightings and how many of them use URL words; a row with neither a page title nor three URL words keeps no title and no flag.

## Real run and first draw (oct.30.2026, Step 5)

- **Ingest.** All 26 case windows were read: 16,909 files and 392,117 matched sightings. Every window is at 99.9–100% except WMT_2022-11-15, at 87.6%. Its 83 files on 2022-11-10/11 are in the master list, but GDELT answers 404 for them, so they are a gap at the source and can't be fixed by retrying. Download speed: about 2 files a second with 8 parallel downloads (PR #51).
- **Events.** Every case has an event run. Clustering compared each article with every event ever opened, which was 20 minutes for one MSFT window; a title-word index made it seconds with identical events (PR #65, checked with `rebuild-events` on the stored runs).
- **Draw 20261030 failed the gate badly.** 612 rows were labelled. The data steward (Sonnet) labelled all of them and the analyst (Opus) labelled 245 blind. `org_exact` precision, the share `about`:

  | Company | AAPL | CAT | JNJ | KO | MSFT | PG | WMT | XOM |
  |---|---|---|---|---|---|---|---|---|
  | Precision | 0.28 | 0.16 | 0.40 | 0.06 | 0.18 | 0.08 | 0.10 | 0.20 |

  Pooled, 73 of 400 `org_exact` rows are `about`. `title_alias` passes only for JNJ (0.92) and PG (0.80 on 5 rows). `org_subsidiary` has no `about` row.
- **The labellers agree on what matters.** Over the 245 shared rows kappa is 0.69 on the three labels and 0.90 on `about` against the rest. Most disagreements are `not` against `related` (32 rows), which doesn't change precision. Some cells are below the 0.6 floor (AAPL, KO, MSFT and WMT). Those cells were not sent to the owner: the gate fails under either labeller's labels, so reading it doesn't depend on who is right.
- **Why it fails.** GDELT's organisation tags catch passing mentions, not stories about the company:
  - "Microsoft" is tagged on 129,379 of the 392,117 sightings: Windows and Teams in sidebars, market-research spam, and so on.
  - The `related` rows are market wraps, "shares acquired by" holdings notices, shopping deals and industry lists.
  - The `not` rows are mostly `title_alias` false friends: Colin the Caterpillar, Coca-Cola recipes and games, Walmart review spam, apple the fruit.
- **Alias fixes can't cure this.** Most failures are the right company in the wrong role, not the wrong company. The design's remedy (alias fixes, `rematch`, a new draw) therefore isn't enough. A first check on this draw: requiring the company's name in the headline keeps 55 of the 73 `about` rows among 74 kept rows, a precision of about 0.74. The misses are possessives ("apples", "procter gambles"), short names ("pg"), products (iPhone, Xbox) and empty titles. The remaining noise is wraps and holdings notices.

## Where the work stopped (oct.30.2026)

- Done: Steps 0–5 up to the first draw, merged in PRs #41, #43, #48, #51 and #65. The draw and its labels are in `domains/news/match_sample.csv`. The gate fails, so M5 is not Done.
- Next, Step 6: a headline rule, as a design amendment with its own review. A matched article feeds events only if:
  - the company's name, a possessive or short form, or one of a short list of its brands appears in the headline (or the URL words when there is no title);
  - and the headline is not a holdings notice or market wrap.

  All matches stay stored. Then draw again with a new seed and label it. The idea for per-cell kappa to use `about` against the rest (what precision reads) goes to the same review.
- The real database is local to the run that made it (`data/` is git-ignored). A fresh run needs about 2.5 hours to download it again.
