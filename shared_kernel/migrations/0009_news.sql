-- 0009: news from GDELT (M5, Decisions 3 and 8). A manifest of the 15-minute files read, every
-- sighting of a matched article (GDELT lists one URL many times), the company matches, and event
-- runs that cluster the sightings known by an as-of date. Times are UTC ISO 8601 with Z.

CREATE TABLE news_files (
    file_url        TEXT PRIMARY KEY,
    file_ts         TEXT NOT NULL,                     -- the file's 15-minute slot, UTC
    md5             TEXT,                              -- from the master list; NULL when missing
    status          TEXT NOT NULL CHECK (status IN ('ok', 'missing', 'bad_md5')),
    rows_total      INTEGER,
    rows_kept       INTEGER,
    aliases_sha256  TEXT NOT NULL,                     -- the alias set the rows were matched with
    fetched_at      TEXT NOT NULL
);

CREATE TABLE articles (
    article_id  TEXT PRIMARY KEY,                      -- SHA-256 of the normalised URL
    url         TEXT NOT NULL,
    source      TEXT NOT NULL                          -- the publisher's domain
);

CREATE TABLE article_sightings (
    article_id   TEXT NOT NULL REFERENCES articles (article_id),
    file_url     TEXT NOT NULL REFERENCES news_files (file_url),
    seen_at      TEXT NOT NULL,                        -- when GDELT processed it
    title        TEXT,
    tone         REAL,
    themes_json  TEXT NOT NULL,
    orgs_json    TEXT NOT NULL,
    PRIMARY KEY (article_id, file_url)
);
CREATE INDEX article_sightings_seen ON article_sightings (seen_at);

CREATE TABLE article_companies (
    article_id  TEXT NOT NULL,
    file_url    TEXT NOT NULL,
    cik         TEXT NOT NULL REFERENCES companies (cik),
    method      TEXT NOT NULL CHECK (method IN ('org_exact', 'org_subsidiary', 'title_alias')),
    PRIMARY KEY (article_id, file_url, cik),
    FOREIGN KEY (article_id, file_url) REFERENCES article_sightings (article_id, file_url)
);

CREATE TABLE event_runs (
    event_run_id  TEXT PRIMARY KEY,
    cik           TEXT NOT NULL REFERENCES companies (cik),
    as_of         DATE NOT NULL,
    tz            TEXT NOT NULL,                       -- the case calendar, e.g. America/New_York
    params_json   TEXT NOT NULL,
    input_sha256  TEXT NOT NULL,                       -- the sightings the run clustered
    code_version  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE events (
    event_id       TEXT PRIMARY KEY,
    event_run_id   TEXT NOT NULL REFERENCES event_runs (event_run_id),
    cik            TEXT NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    article_count  INTEGER NOT NULL,
    source_count   INTEGER NOT NULL,
    label          TEXT,
    themes_json    TEXT NOT NULL,
    median_tone    REAL,
    event_type     TEXT,                               -- M6
    summary        TEXT                                -- M6
);

CREATE TABLE event_articles (
    event_id    TEXT NOT NULL REFERENCES events (event_id),
    article_id  TEXT NOT NULL REFERENCES articles (article_id),
    PRIMARY KEY (event_id, article_id)
);

-- keyword search over titles; queries join back to article_sightings to apply as_of
CREATE VIRTUAL TABLE sightings_fts USING fts5 (title, content = 'article_sightings');
CREATE TRIGGER sightings_fts_insert AFTER INSERT ON article_sightings BEGIN
    INSERT INTO sightings_fts (rowid, title) VALUES (new.rowid, new.title);
END;
CREATE TRIGGER sightings_fts_delete AFTER DELETE ON article_sightings BEGIN
    INSERT INTO sightings_fts (sightings_fts, rowid, title) VALUES ('delete', old.rowid, old.title);
END;
