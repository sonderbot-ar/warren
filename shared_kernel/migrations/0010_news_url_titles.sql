-- 0010: GDELT has no page titles before about October 2019, so a sighting may carry headline
-- words taken from its URL instead (M5 Step 5). Flagged, so reports and matching can tell.

ALTER TABLE article_sightings ADD COLUMN title_from_url INTEGER NOT NULL DEFAULT 0;
