"""The evaluation reports show changes of reporting basis apart (backlog #162), on Test Corp:
with the Q3 2019 10-Q recasting the year-earlier quarter's revenue by 5%, that one quarter is
flagged; without the recast, none is. The headline tables are unchanged either way."""

from datetime import date

from domains.evaluation import report
from domains.evaluation.harness import run_batch
from tests.evaluation.conftest import CHOICES
from tests.evaluation.test_harness import TODAY, case


def recast(tag, row):
    if tag == "Revenues" and row["end"] == "2018-09-30" and row["fy"] == 2019:
        row = row | {"val": row["val"] * 1.05}
    return row


def batch(conn):
    return run_batch(conn, [case()], "abc", CHOICES, actuals_as_of=TODAY, today=TODAY)


def headline(text):
    return text.split("## Headline")[1].split("## Segments")[0]


def test_a_recast_quarter_is_counted_segmented_and_flagged(make_company):
    conn = make_company(recast)
    text = report.render(conn, batch(conn))
    assert "Changes of basis: 1 of 8 scored rows" in text
    (seg,) = [line for line in text.splitlines() if line.startswith("| Without changes of basis")]
    assert "(n=3)" in seg and "(n=4)" in seg  # revenue loses FY2019Q3, EBIT keeps all four
    rows = [x for x in text.splitlines() if x.startswith("| TST_2019-06-30 |")]
    (q3,) = [x for x in rows if "FY2019Q3 | 2 | revenue" in x]
    assert q3.rstrip(" |").endswith("basis change")
    assert "**Change of basis:**" in text


def test_the_headline_is_unchanged_by_the_flag(make_company):
    """The flag is shown beside the headline, never taken out of it (that is the owner's card):
    the recast quarter still counts in the revenue headline, at the same median error."""
    plain, recast_conn = make_company(None), make_company(recast)
    a, b = report.render(plain, batch(plain)), report.render(recast_conn, batch(recast_conn))

    def cells(text):  # item, horizon, n, baseline and naive medians of the all-horizons rows
        return [line.split(" | ")[:5] for line in headline(text).splitlines()
                if line.startswith("| ") and " | all | " in line]  # fmt: skip

    assert cells(a) == cells(b) and [c[2] for c in cells(b)] == ["4", "4"]
    assert "Changes of basis: none of 8 scored rows" in a
    assert "basis change" not in a.split("## Every case")[1].split("## Glossary")[0]


def test_counts_skip_unscored_quarters(make_company):
    conn = make_company(recast)
    batch_id = run_batch(conn, [case(event_date=date(2019, 9, 30))], "abc", CHOICES,
                         actuals_as_of=TODAY, today=TODAY)  # fmt: skip
    n, scored, _ = report.basis_counts(report.load_rows(conn, batch_id))
    assert scored == len([r for r in report.load_rows(conn, batch_id)
                          if r["variant"] == "baseline" and r["status"] == "ok"])  # fmt: skip
    assert n <= scored
