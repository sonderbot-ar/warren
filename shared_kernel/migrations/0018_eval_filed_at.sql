-- 0018: the date each scored actual was filed (M10). One nullable column; no stored row changes.
--
-- eval_results.actual_filed_at: the latest filing among the actual's inputs (harness.Actual
-- filed_at), so a report can tell whether an outcome was public before a model's training cutoff
-- (the M10 memory test). Rows stored before this migration keep NULL, and `reproduce --batch`
-- compares the column only where it was stored. Design: docs/designs/m10-more-dates.md.

ALTER TABLE eval_results ADD COLUMN actual_filed_at DATE;
