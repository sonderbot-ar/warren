-- foreign_keys: off
-- 0011: a file we failed to download is `fetch_error`, apart from `missing`, a file GDELT never
-- published or no longer serves (backlog #52). SQLite can't change a CHECK in place, so
-- news_files is rebuilt with foreign keys off; the runner checks every foreign key before commit.
-- Rows from before 0011 keep their status: an old `missing` can't be split after the fact.

CREATE TABLE news_files_0011 (
    file_url        TEXT PRIMARY KEY,
    file_ts         TEXT NOT NULL,                     -- the file's 15-minute slot, UTC
    md5             TEXT,                              -- from the master list; NULL when missing
    status          TEXT NOT NULL
                    CHECK (status IN ('ok', 'missing', 'bad_md5', 'fetch_error')),
    rows_total      INTEGER,
    rows_kept       INTEGER,
    rows_bad        INTEGER,                           -- rows that couldn't be parsed, skipped
    aliases_sha256  TEXT NOT NULL,                     -- the alias set the rows were matched with
    fetched_at      TEXT NOT NULL
);

INSERT INTO news_files_0011 (file_url, file_ts, md5, status, rows_total, rows_kept, rows_bad,
                             aliases_sha256, fetched_at)
SELECT file_url, file_ts, md5, status, rows_total, rows_kept, rows_bad, aliases_sha256, fetched_at
FROM news_files;

DROP TABLE news_files;
ALTER TABLE news_files_0011 RENAME TO news_files;
