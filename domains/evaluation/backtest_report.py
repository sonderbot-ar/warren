"""Markdown report of a backtest batch (M8), built from the database alone.

The headline is fixed in the design before any result was seen: per item, the skill score
against the baseline and the per-case sign test, on all cases, for the masked variant, with the
named variant beside it. Everything else is context or descriptive. Design:
docs/designs/m8-backtest.md.
"""

import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from domains.evaluation import backtest as bt
from domains.evaluation import grid
from domains.evaluation import grid_report as gr
from domains.evaluation.backtest_batch import LLM_VARIANTS, batch_notes
from domains.evaluation.report import REPORTS_DIR, load_rows
from domains.llm import review
from shared_kernel.config import NODE_MODELS

ITEMS = ("revenue", "ebit")
ITEM_NAMES = {"revenue": "Revenue", "ebit": "EBIT"}
UNITS = {"revenue": "% of actual revenue", "ebit": "margin points"}
SHOCKED = ("llm_masked", "llm_named", "with_shocks")
NAMES = {"llm_masked": "AI, masked", "llm_named": "AI, named", "with_shocks": "Guidance",
         "baseline": "Baseline", "naive_srw": "Naive (same quarter last year)"}  # fmt: skip


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _pts(x: float | None, digits: int = 2) -> str:
    """An error difference in points (revenue: % points of APE; EBIT: margin points)."""
    return "n/a" if x is None else f"{x * 100:+.{digits}f}"


def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _interval(iv: tuple[float, float] | None) -> str:
    return "n/a" if iv is None else f"{_pts(iv[0])} to {_pts(iv[1])}"


def case_info(conn: sqlite3.Connection, batch_id: str) -> dict[str, sqlite3.Row]:
    return {
        r["case_id"]: r
        for r in conn.execute(
            "SELECT c.* FROM eval_cases c WHERE c.case_id IN "
            "(SELECT case_id FROM eval_results WHERE batch_id = ?)",
            (batch_id,),
        )
    }


def drivers(conn: sqlite3.Connection, notes: dict) -> dict[tuple[str, str], list]:
    """(case, llm variant) → the shocks applied, in stored order."""
    out = {}
    for case_id, set_ids in notes["sets"].items():
        for v, set_id in set_ids.items():
            out[(case_id, LLM_VARIANTS[v])] = review.approved_shocks(conn, set_id)
    return out


def _shock_words(shocks: list) -> str:
    if not shocks:
        return "none"
    names = {"revenue_growth": "revenue", "operating_margin": "margin",
             "capex_intensity": "capex", "risk_premium": "risk premium"}  # fmt: skip
    return ", ".join(f"{names[s.driver]} {'up' if s.base > 0 else 'down'}" for s in shocks)


def _headline(rows, variant, population, scope_cases, naive) -> list[str]:
    out = []
    for item, ps in sorted(bt.by_item(bt.pairs(rows, variant, population, scope_cases)).items(),
                           key=lambda kv: ITEMS.index(kv[0])):  # fmt: skip
        ds = list(bt.case_differences(ps).values())
        sk = bt.skill(ps)
        t = bt.sign_test(ds)
        out.append(
            f"| {NAMES[variant]} | {ITEM_NAMES[item]} | {len(ds)} / {len(ps)} | "
            f"{_pct(sk[0]) if sk else 'n/a'} | {_pct(sk[1]) if sk else 'n/a'} | "
            f"{_pct(bt.skill_against(ps, naive))} | {t.better} / {t.worse} / {t.ties} | "
            f"{_p(t.p)} | {_pts(statistics.fmean(ds)) if ds else 'n/a'} | "
            f"{_interval(bt.bootstrap_mean(ds))} |"
        )
    return out


HEADLINE_HEAD = [
    "| Variant | Item | Cases / quarters | Skill (mean) | Skill (median) | Skill vs naive | "
    "Better / worse / tied cases | Sign test p | Mean d | 90% interval of mean d |",
    "|---|---|---|---|---|---|---|---|---|---|",
]


def render(conn: sqlite3.Connection, batch_id: str) -> str:
    notes = batch_notes(conn, batch_id)
    rows = load_rows(conn, batch_id)
    batch = conn.execute("SELECT * FROM eval_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    failures = conn.execute(
        "SELECT case_id, reason FROM eval_failures WHERE batch_id = ? ORDER BY case_id",
        (batch_id,),
    ).fetchall()
    info = case_info(conn, batch_id)
    scope_cases = {c for c, r in info.items() if r["scope_change"]}
    shocks = drivers(conn, notes)
    naive = {(r["case_id"], r["item"], r["period"]): r for r in rows
             if r["variant"] == "naive_srw"}  # fmt: skip
    scored = sorted({r["case_id"] for r in rows})
    out = [
        f"# Backtest {batch_id}",
        "",
        f"Code version `{batch['code_version']}`; actuals as first reported up to "
        f"{notes['actuals_as_of']}; {notes['n_samples']:,} samples per simulation, one seed per "
        f"case. {len(scored)} cases scored, {len(failures)} failed.",
        "",
        "**The question:** does adding the AI's news shocks make the baseline forecast of the "
        "next 1–4 quarters better? Errors: revenue in % of the actual, EBIT in margin points "
        "(EBIT error ÷ actual revenue). d is a case's mean error with shocks minus its mean "
        "error without; below 0, the shocks helped on that case.",
        "",
        "## Headline: all cases",
        "",
        "Every scored case counts. Where the AI proposed nothing that applies, its forecast is "
        "the baseline's, which is what a user would have got. The headline is the masked "
        "variant (the smaller leak of the model's memory), with named beside it. Guidance "
        "shocks are judged on their own cases only; with 3 cases a sign test can't go below "
        "p = 0.25.",
        "",
        *HEADLINE_HEAD,
    ]
    for v in SHOCKED:
        out += _headline(rows, v, "all", scope_cases, naive)
    out += [
        "",
        "Skill = 1 − mean error with shocks ÷ mean error without, over the same quarters "
        "(above 0 is better); the median version uses medians. The sign test counts cases, "
        "because a case's quarters share one run and one set of shocks; tied cases (no change) "
        "are left out of it. The interval is a case bootstrap (10,000 draws, fixed seed); with "
        "this few cases it tends to be too narrow.",
        "",
        "## Where the shocks moved the forecast",
        "",
        "Only the cases and items whose forecast the shocks changed (risk-premium and capex "
        "shocks move neither revenue nor EBIT). This view is chosen by the AI's own decisions, "
        "so it is context, not the answer.",
        "",
        *HEADLINE_HEAD,
    ]
    for v in SHOCKED[:2]:
        out += _headline(rows, v, "moved", scope_cases, naive)
    out += [
        "",
        "## Without deals closing inside the horizon",
        "",
        "Cases whose horizon holds an acquisition or divestiture closing "
        f"({', '.join(sorted(scope_cases)) or 'none'}) are left out: there the baseline can't "
        "see the acquired revenue, so a shock that adds it wins almost by construction.",
        "",
        *HEADLINE_HEAD,
    ]
    for v in SHOCKED[:2]:
        out += _headline(rows, v, "no_scope", scope_cases, naive)

    def reference(population: str) -> str:
        ps = bt.pairs(rows, "baseline", population, scope_cases)
        return "; ".join(
            f"{ITEM_NAMES[i]} {_pct(bt.skill_against(q, naive))}"
            for i, q in sorted(bt.by_item(ps).items(), key=lambda kv: ITEMS.index(kv[0]))
        )

    out += [
        "",
        f"For reference, the baseline's skill against the naive forecast: all cases "
        f"{reference('all')}; without deals {reference('no_scope')}.",
        "",
        "## By horizon",
        "",
        "Mean of (error with shocks − error without) by quarter ahead, all cases. A shock that "
        "starts in quarter 2 leaves quarter 1 unchanged.",
        "",
        "| Variant | Item | h1 | h2 | h3 | h4 |",
        "|---|---|---|---|---|---|",
    ]
    for v in SHOCKED[:2]:
        for item, ps in sorted(bt.by_item(bt.pairs(rows, v)).items(),
                               key=lambda kv: ITEMS.index(kv[0])):  # fmt: skip
            h = bt.by_horizon(ps)
            cells = [f"{_pts(h[k][0])} (n={h[k][1]})" if k in h else "n/a" for k in (1, 2, 3, 4)]
            out.append(f"| {NAMES[v]} | {ITEM_NAMES[item]} | {' | '.join(cells)} |")
    if info and all(r["event_type"] == "grid" for r in info.values()):
        out += grid_sections(conn, rows, {f["case_id"]: f["reason"] for f in failures})
    out += _direction(rows)
    out += _band(rows)
    out += _groups(rows, info, shocks)
    out += _named_masked(rows, scored)
    out += _per_case(rows, info, shocks)
    if failures:
        out += ["", "## Failed cases", ""] + [f"- {f['case_id']}: {f['reason']}" for f in failures]
    out += _glossary()
    return "\n".join(out) + "\n"


def _direction(rows) -> list[str]:
    out = [
        "",
        "## Direction",
        "",
        "Up, flat or down against the same quarter a year earlier (within ±0.5% is flat). The "
        'base rate is the share of quarters that rose: the score of always saying "up". '
        "The naive forecast repeats last year's quarter, so it always says flat; it is shown "
        "only as a floor.",
        "",
        "| Variant | Item | Hit rate | Quarters | Base rate | Direction unknown |",
        "|---|---|---|---|---|---|",
    ]
    for v in ("baseline", "naive_srw", *SHOCKED):
        for item in ITEMS:
            if v in ("baseline", "naive_srw"):
                chosen = [r for r in rows if r["variant"] == v and r["status"] == "ok"
                          and r["item"] == item]  # fmt: skip
            else:  # all cases: the baseline's forecast where the variant has none
                chosen = [p.variant for p in bt.pairs(rows, v) if p.item == item]
            if not chosen:
                continue
            d = bt.direction(chosen)
            out.append(f"| {NAMES[v]} | {ITEM_NAMES[item]} | {_pct(d.rate)} | {d.n} | "
                       f"{_pct(d.base_rate)} | {d.unknown} |")  # fmt: skip
    return out


def _band(rows) -> list[str]:
    out = [
        "",
        "## The p10–p90 band",
        "",
        "**Read this first.** The band covers only the uncertainty in the size of the shocks. "
        "The baseline itself is not sampled, so a quarter no shock touches has a band of zero "
        "width. Decision 7 asks that about 80% of actuals fall inside a calibrated band; this "
        "band is not built to pass that check, and the numbers below show how far it is from "
        "it. The interval score adds the band's width to 10 times any miss (lower is better; "
        "in % of actual revenue for both items); the baseline is scored as a band of zero "
        "width on the same quarters.",
        "",
        "| Variant | Item | Coverage, all quarters | 95% interval | Coverage, quarters a shock "
        "widened | Interval score: band / baseline (quarters) |",
        "|---|---|---|---|---|---|",
    ]
    for v in SHOCKED:
        for item in ITEMS:
            mine = [r for r in rows if r["variant"] == v and r["item"] == item]
            if not mine:
                continue
            c = bt.coverage(mine)
            wide = bt.coverage([r for r in mine if bt.is_wide(r)])
            ps = [p for p in bt.pairs(rows, v) if p.item == item]
            iscore = bt.interval_scores(ps)
            score_text = (
                f"{_pct(iscore[0], 2)} / {_pct(iscore[1], 2)} ({iscore[2]})" if iscore else "n/a"
            )
            out.append(
                f"| {NAMES[v]} | {ITEM_NAMES[item]} | {_pct(c.share)} ({c.inside} of {c.n}) | "
                f"{_interval_pct(c.interval)} | {_pct(wide.share)} ({wide.inside} of {wide.n}) | "
                f"{score_text} |"
            )
    return out


def _interval_pct(iv) -> str:
    return "n/a" if iv is None else f"{_pct(iv[0], 0)}–{_pct(iv[1], 0)}"


def _groups(rows, info, shocks) -> list[str]:
    out = [
        "",
        "## By event type and by driver (descriptive only)",
        "",
        "One to eight cases per type: these tables describe, they can't show anything. Mean d "
        "over the cases of the group, all cases view. A case's d is the effect of all its "
        "shocks together, so a case with shocks on two drivers is in both driver groups with "
        "the same d.",
        "",
        "| Group | Cases | Masked: revenue d | Masked: EBIT d | Named: revenue d | Named: EBIT d |",
        "|---|---|---|---|---|---|",
    ]
    diffs = {}
    for v in SHOCKED[:2]:
        for item, ps in bt.by_item(bt.pairs(rows, v)).items():
            diffs[(v, item)] = bt.case_differences(ps)
    groups: dict[str, set[str]] = defaultdict(set)
    for case_id, r in info.items():
        groups[f"type: {r['event_type']}"].add(case_id)
    for (case_id, _), shock_list in shocks.items():
        for s in shock_list:
            groups[f"driver: {s.driver}"].add(case_id)
    for name in sorted(groups):
        cases = groups[name]
        cells = []
        for v in SHOCKED[:2]:
            for item in ITEMS:
                ds = [diffs.get((v, item), {}).get(c) for c in cases]
                ds = [d for d in ds if d is not None]
                cells.append(_pts(statistics.fmean(ds)) if ds else "n/a")
        out.append(f"| {name} | {len(cases)} | {' | '.join(cells)} |")
    controls = sorted(c for c, r in info.items() if r["event_type"] == "control")
    noisy = [(c, v) for c in controls for v in SHOCKED[:2] if shocks.get((c, v))]
    out += [
        "",
        f"**Controls** are rule-dated quiet days, where shocks should do nothing. Shocks on "
        f"controls: {len(noisy)} of {2 * len(controls)} sets"
        + (
            ": " + "; ".join(f"{c} {NAMES[v]} ({_shock_words(shocks[(c, v)])})" for c, v in noisy)
            if noisy
            else ""
        )  # fmt: skip
        + ".",
    ]
    return out


def _named_masked(rows, scored) -> list[str]:
    flips = bt.opposite_moves(rows)
    cutoffs = sorted({m.training_cutoff for m in NODE_MODELS.values() if m.training_cutoff})
    first = cutoffs[0] if cutoffs else None
    # post-cutoff: the whole news week after the cutoff month (M10 rule, grid.is_post_cutoff)
    post = [c for c in scored if first and grid.is_post_cutoff(gr.case_date(c))]
    return [
        "",
        "## Named against masked",
        "",
        "The masked variant hides the company's name, ticker and dates from the AI. The gap "
        "between the two mixes the model's memory of what happened next with the distraction "
        "of the name itself, so it is not a clean measure of look-ahead.",
        "",
        f"- Items moved in opposite directions by the two variants: {len(flips)}, in "
        f"{len({c for c, _ in flips})} cases"
        + (" (" + ", ".join(f"{c} {ITEM_NAMES[i]}" for c, i in flips) + ")" if flips else "")
        + ".",
        f"- Cases dated after the models' training cutoff ({first or 'not recorded'}): "
        f"{len(post)} of {len(scored)}. Every case could be in the models' memory.",
    ]


def _per_case(rows, info, shocks) -> list[str]:
    out = [
        "",
        "## Case by case",
        "",
        "d per case (error with shocks − without, in points); blank where the AI's shocks "
        "didn't change that item.",
        "",
        "| Case | Type | Masked shocks | Named shocks | Masked: revenue d | Masked: EBIT d | "
        "Named: revenue d | Named: EBIT d |",
        "|---|---|---|---|---|---|---|---|",
    ]
    diffs = {}
    for v in SHOCKED[:2]:
        for item, ps in bt.by_item(bt.pairs(rows, v, "moved")).items():
            diffs[(v, item)] = bt.case_differences(ps)
    for case_id in sorted(info):
        cells = []
        for v in SHOCKED[:2]:
            for item in ITEMS:
                d = diffs.get((v, item), {}).get(case_id)
                cells.append("" if d is None else _pts(d))
        out.append(
            f"| {case_id} | {info[case_id]['event_type']} | "
            f"{_shock_words(shocks.get((case_id, 'llm_masked'), []))} | "
            f"{_shock_words(shocks.get((case_id, 'llm_named'), []))} | {' | '.join(cells)} |"
        )
    return out


def _date_line(name: str, item: str, t: gr.DateTest) -> str:
    return (
        f"| {name} | {ITEM_NAMES[item]} | {t.cases} / {t.dates} | {_pts(t.mean_d)} | "
        f"{t.sign.better} / {t.sign.worse} / {t.sign.ties} | {_p(t.sign.p)} | "
        f"{_interval(t.interval)} | {_interval(t.block)} | {'shown' if t.shown else 'not shown'} |"
    )


DATE_HEAD = [
    "| Variant | Item | Cases / dates | Mean d | Dates better / worse / tied | Sign test p "
    "(dates) | 90% interval (date bootstrap) | 90% interval (blocks of 4 dates) | Gain |",
    "|---|---|---|---|---|---|---|---|---|",
]


def _ds(rows, variant, keep=None) -> dict[str, dict[str, float]]:
    out = {}
    for item, ps in bt.by_item(bt.pairs(rows, variant)).items():
        ds = bt.case_differences(ps)
        out[item] = {c: d for c, d in ds.items() if keep is None or keep(c)}
    return out


def grid_sections(conn: sqlite3.Connection, rows: list[dict], failures: dict[str, str]) -> list:
    """The M10 sections: date-clustered tests, pre/post cutoff, the memory test, the h1 split and
    the counts. Fixed in docs/designs/m10-more-dates.md before any result."""
    case_ids = sorted({r["case_id"] for r in rows} | set(failures))
    c = gr.counts(case_ids, rows, failures)
    post = [x for x in case_ids if grid.is_post_cutoff(gr.case_date(x))]
    out = [
        "",
        "## Grid cases: the test read for the answer",
        "",
        f"{c.cases} grid cases in the batch ({len(case_ids) - len(post)} before the models' "
        f"cutoff, {len(post)} after): {c.scored} scored, {len(c.not_yet_scorable)} not yet "
        f"scorable (no actual reported yet), {len(c.failed)} failed. Cases left out by the "
        "grid rule are listed by `python -m domains.evaluation grid`.",
        "",
        "The companies on one date share a news week and its surprises, so the test is read at "
        "the level of dates: the sign test on each date's mean d, and intervals that resample "
        "whole dates. A gain is **shown** when that sign test has p < 0.05 and the date interval "
        "excludes zero; otherwise it is **not shown**, which is not the same as no effect.",
        "",
        *DATE_HEAD,
    ]
    for v in SHOCKED[:2]:
        for item, ds in sorted(_ds(rows, v).items(), key=lambda kv: ITEMS.index(kv[0])):
            out.append(_date_line(NAMES[v], item, gr.date_test(ds)))
    out += ["", "### Before and after the models' cutoff", "", *DATE_HEAD]
    for label, keep in (("before", lambda x: grid.is_pre_cutoff(gr.case_date(x))),
                        ("after", lambda x: grid.is_post_cutoff(gr.case_date(x)))):  # fmt: skip
        for v in SHOCKED[:2]:
            for item, ds in sorted(_ds(rows, v, keep).items(), key=lambda kv: ITEMS.index(kv[0])):
                out.append(_date_line(f"{NAMES[v]}, {label}", item, gr.date_test(ds)))
    gaps = gr.memory_gaps(rows)
    out += [
        "",
        "### The memory test (h1 only)",
        "",
        "g = (error with the named variant's shocks − without) − (the same for masked), at the "
        "first forecast quarter. Below 0, naming the company helped more. If the named edge came "
        "from the model remembering outcomes, g would be below 0 when the outcome was public "
        "before the cutoff (A) and near 0 when it wasn't (B, C). Masking doesn't fully stop "
        "recall, so g understates memory; few dates sit after the cutoff, so a missing change "
        'is "not shown", never "no memory".',
        "",
        "| Item | Group | Cases / dates | Mean g | 90% interval (date bootstrap) |",
        "|---|---|---|---|---|",
    ]
    for item in ITEMS:
        for g in gr.GROUPS:
            ds = gaps.get(item, {}).get(g, {})
            t = gr.date_test(ds)
            out.append(f"| {ITEM_NAMES[item]} | {g}: {gr.GROUP_NAMES[g]} | {t.cases} / {t.dates}"
                       f" | {_pts(t.mean_d)} | {_interval(t.interval)} |")  # fmt: skip
        a, cc = gaps.get(item, {}).get("A", {}), gaps.get(item, {}).get("C", {})
        if a and cc:
            diff = statistics.fmean(cc.values()) - statistics.fmean(a.values())
            out.append(f"| {ITEM_NAMES[item]} | C − A | | {_pts(diff)} | |")
    out += [
        "",
        "### First quarter: already ended or still running",
        "",
        "On some dates the first forecast quarter had already ended (a nowcast). Mean d at h1:",
        "",
        "| Variant | Item | Ended: cases, mean d | Running: cases, mean d |",
        "|---|---|---|---|",
    ]
    for v in SHOCKED[:2]:
        effects = gr.h1_effects(rows, v)
        for item in ITEMS:
            parts = []
            for closed in (True, False):
                e = [d for (cid, it), (d, b) in effects.items()
                     if it == item and gr.h1_closed(b) is closed]  # fmt: skip
                parts.append(f"{len(e)}, {_pts(statistics.fmean(e)) if e else 'n/a'}")
            out.append(f"| {NAMES[v]} | {ITEM_NAMES[item]} | {parts[0]} | {parts[1]} |")
    sql = "SELECT case_id, MAX(events_chosen) AS n FROM case_llm_status GROUP BY case_id"
    chosen = {r["case_id"]: r["n"] for r in conn.execute(sql)}
    out += ["", "### Quiet weeks", "", "| Variant | Shocks | Events, no shock | No events |",
            "|---|---|---|---|"]  # fmt: skip
    for v in SHOCKED[:2]:
        q = gr.quiet(rows, chosen, v)
        out.append(f"| {NAMES[v]} | {len(q['shocks'])} | {len(q['no shock'])} | "
                   f"{len(q['no events'])} |")  # fmt: skip
    if c.not_yet_scorable:
        out += ["", "Not yet scorable: " + ", ".join(c.not_yet_scorable) + "."]
    return out


def _glossary() -> list[str]:
    return [
        "",
        "## Glossary and limitations",
        "",
        "- **Skill score:** 1 − (mean error of the forecast ÷ mean error of the reference). 0 is "
        "no better, 10% is a tenth less error, negative is worse.",
        "- **Sign test:** counts the cases where the shocks helped and where they hurt; p is "
        "the chance of a split at least this lopsided if the shocks made no difference.",
        "- **Case bootstrap:** resamples whole cases to show how much the mean of d could move "
        "with a different draw of cases.",
        "- **Coverage:** the share of actuals inside the p10–p90 band.",
        "- **Interval score:** width of the band plus 10 × how far the actual fell outside.",
        "- **Limitations:** events were chosen in hindsight as notable; 26 cases is few, so "
        "most differences can't be told from chance; the AI may remember what happened next, "
        "masked or not; the band covers shock size only; the shock sizes were set before any "
        "result and never tuned on these cases.",
    ]


def write_report(conn: sqlite3.Connection, batch_id: str, directory: Path = REPORTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{batch_id}_backtest.md"
    path.write_text(render(conn, batch_id))
    return path
