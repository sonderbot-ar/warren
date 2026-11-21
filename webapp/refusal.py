"""*No se pudo*: why the engine refused an estimate, in the student's words (F2 Step 4b, part 3b).

The engine refuses a run with a code and params (`domains.analysis.coded.refusal`, backlog
#376), never with words for a student. This module turns that code into the brief's three
things, in order ("When an estimate can't be built", `docs/product/brief.md`): a title from the
code's group that names what the student can do, one sentence that names the cause on this
company and date, and one button that does what the title says; under them, a "¿Por qué?"
lesson (`domains.analysis.text.refusal_lesson`) with its source.

No words here: every text is a catalogue key (`refusal.*`), and every date and number from the
engine's params goes through `formatting`, so the sentence reads in the student's region. A
code the catalogue has no sentence for, or a refusal with no code, gets the generic sentence:
a wrong cause misleads more than none. The catalogue test keeps the first from happening.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from domains.analysis.coded import REFUSAL_GROUPS, Coded
from domains.analysis.text import REFUSAL_LESSONS, refusal_lesson
from webapp import formatting

GENERIC = "generic"  # the "group" of a refusal with no code, or a code with no Spanish

# Button kinds: compute again on another date (a form that posts to /calcular), change the
# reading (a link to the card with its menus open), or open the lesson in place.
BUTTON_DATE = "date"
BUTTON_MENUS = "menus"
BUTTON_WHY = "why"


@dataclass(frozen=True)
class Button:
    kind: str
    label: str
    corte: date | None = None  # BUTTON_DATE: the date to compute on


@dataclass(frozen=True)
class Lesson:
    why: str
    source: str  # the published source, or Warren's own criterion said as such
    own_rule: bool  # a working rule of Warren's, not a published norm


@dataclass(frozen=True)
class RefusalView:
    group: str
    code: str | None
    title: str
    sentence: str
    button: Button | None
    lesson: Lesson | None
    setup_note: str | None = None  # the `setup` group's "this doesn't depend on you"
    extra: list[str] = field(default_factory=list)  # further sentences (a derived quarter)


def _day(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def _fiscal_year(period: str) -> str:
    """ "FY2018" -> "2018"; "FY2017-FY2019" -> the two years for the range sentence."""
    return period.replace("FY", "")


def _sentence(
    code: str, p: dict, company: str, corte: date, region, t: Callable[..., str]
) -> tuple[str, list[str]]:
    """The cause on this company and date, and any further sentence; KeyError when the
    catalogue has no sentence for the code or its variant (the caller falls back)."""
    d = lambda key: formatting.format_date(date.fromisoformat(p[key]), region)  # noqa: E731
    n = lambda value: formatting.count(value, region)  # noqa: E731
    money = lambda value: formatting.figure(value, "millions", region)  # noqa: E731
    base = {"empresa": company, "fecha": formatting.format_date(corte, region)}
    key = f"refusal.code.{code}"
    extra: list[str] = []
    if code == "as_of_too_early":
        params = {"supported_from": d("supported_from"), "as_of": d("as_of")}
    elif code == "as_of_in_future":
        params = {"as_of": d("as_of"), "today": d("today")}
    elif code == "history_too_short":
        years = p.get("found_years") or []
        params = {"needed": n(p["needed"]), "found": n(len(years))}
        if not years:
            key += ".none"
        else:
            params["years"] = t("refusal.list_sep").join(str(y) for y in years)
    elif code in ("too_few_comparatives", "too_few_return_weeks"):
        params = {"needed": n(p["needed"]), "found": n(p["found"])}
    elif code == "too_few_quarters":
        params = {
            "quarter": p["quarter"],
            "needed": n(p["needed"]),
            "found": n(p["found"]),
            "window": n(p["window"]),
        }
    elif code == "erp_too_few_years":
        params = {
            "min_years": n(p["min_years"]),
            "first_year": p["first_year"],
            "last_year": p["last_year"],
            "first_as_of": d("first_as_of"),
        }
    elif code == "market_data_not_refreshed":
        if p.get("all_covered_through"):
            params = {"through": d("all_covered_through")}
        else:
            key += ".one"
            params = {"through": d("covered_through")}
    elif code == "seed_quarter_not_reported":
        params = {"quarter": p["quarter"], "fiscal_year": p["fiscal_year"]}
    elif code in ("flow_item_not_reported", "balance_item_not_reported"):
        if p.get("period_end"):
            key += ".date"
            params = {"period_end": d("period_end")}
        else:
            key += ".quarter" if p.get("quarter") else ".year"
            params = {"quarter": p.get("quarter"), "fiscal_year": p["fiscal_year"]}
    elif code == "no_share_count":
        key += f".{p['reason']}"
        params = {}
    elif code == "no_interest_with_debt":
        params = {"years": t("refusal.list_sep").join(str(y) for y in p["fiscal_years"])}
    elif code == "zero_divisor":
        kind = p["period_kind"]
        key += f".{kind}"
        params = {"ratio": t(f"refusal.ratio.{p['ratio']}")}
        if kind in ("quarter", "year"):
            params["divisor"] = t(f"refusal.divisor.{p['divisor']}")
            params["period_end"] = d("period_end")
            if p.get("accession_no") is None and p.get("inputs"):
                extra.append(t("refusal.code.zero_divisor.derived"))
        elif kind == "quarters_sum":
            params["fiscal_year"] = _fiscal_year(p["period"])
        else:  # years_sum: the divisor names the sentence (revenue or pretax income)
            key += f".{p['divisor']}"
            first, _, last = _fiscal_year(p["period"]).partition("-")
            params["first"], params["last"] = first, last or first
    elif code == "balance_item_negative":
        params = {"period_end": d("period_end"), "value": money(p["value"]),
                  "currency": p["currency"]}  # fmt: skip
    elif code == "securities_exceed_current_assets":
        key += ".with_cash" if p.get("with_cash") else ".alone"
        params = {"period_end": d("period_end"), "securities": money(p["securities"]),
                  "current_assets": money(p["current_assets"]),
                  "currency": p["currency"]}  # fmt: skip
    elif code == "market_year_end_missing":
        params = {"year": p["year"]}
    elif code == "no_base_value":
        key += f".{p['reason']}"
        params = {}
    else:  # the codes whose sentence needs only the company and the date
        params = {}
    return t(key, **base, **params), extra


def _button(group: str, code: str | None, p: dict, latest: date, region, t) -> Button | None:
    if group == "later_date":
        if code == "as_of_too_early":
            return Button(BUTTON_DATE, t("refusal.group.later_date.button"),
                          _day(p["supported_from"]))  # fmt: skip
        if code == "erp_too_few_years":
            first = _day(p["first_as_of"])
            if first > latest:  # that date has not ended yet: no button (brief)
                return None
            label = t("refusal.button.try_date", date=formatting.format_date(first, region))
            return Button(BUTTON_DATE, label, first)
        # the newest ended day has the most history behind it
        return Button(BUTTON_DATE, t("refusal.group.later_date.button"), latest)
    if group == "earlier_date":
        through = (
            _day(p.get("all_covered_through") or p.get("covered_through"))
            if code == "market_data_not_refreshed"
            else latest
        )
        if through is None:
            return None
        return Button(BUTTON_DATE, t("refusal.group.earlier_date.button"), min(through, latest))
    if group == "no_value":
        return Button(BUTTON_WHY, t("refusal.group.no_value.button"))
    if group == "setup":
        return None
    return Button(BUTTON_MENUS, t(f"refusal.group.{group}.button"))


def _lesson(group: str, code: str | None, region, t) -> Lesson | None:
    """The "¿Por qué?" lesson: the code's own when the engine has one, else its group's. The
    `setup` lesson would repeat the screen's words, so it is left out (brief)."""
    if group in (GENERIC, "setup"):
        return None
    engine = refusal_lesson(code)
    key = f"refusal.lesson.{code}" if code in REFUSAL_LESSONS else f"refusal.lesson.{group}"
    params = {}
    if code == "erp_too_few_years":
        # fractions as the brief shows them: sd 0.2 as "20%", se 0.06 and two_se 0.13 as points
        params = {
            "min_years": formatting.count(engine.params["min_years"], region),
            "sd": formatting.count(round(engine.params["sd"] * 100), region),
            "se": formatting.count(round(engine.params["se"] * 100), region),
            "two_se": formatting.count(round(engine.params["two_se"] * 100), region),
        }
    sources = []
    if engine.reference:
        sources.append(t(f"{key}.source"))
    if engine.warren_rule:
        sources.append(t("refusal.own_rule"))
    return Lesson(
        why=t(key, **params),
        source=t("refusal.source_sep").join(sources),
        own_rule=engine.warren_rule is not None,
    )


def refusal_view(
    refused: Coded | None,
    company: str,
    corte: date,
    latest: date,
    region: formatting.Region,
    t: Callable[..., str],
) -> RefusalView:
    """The refusal screen for one company and fecha de corte. `refused` is the engine's coded
    refusal (None when the error had no code); `latest` is the last ended New York day, the
    newest date a button may offer."""
    code = refused.code if refused is not None else None
    group = REFUSAL_GROUPS.get(code, GENERIC) if code else GENERIC
    p = refused.params if refused is not None else {}
    extra: list[str] = []
    try:
        if group == GENERIC:
            raise KeyError(code)
        sentence, extra = _sentence(code, p, company, corte, region, t)
    except (KeyError, TypeError, ValueError):
        # no Spanish for this code, or params the sentence can't read: the generic sentence,
        # never a wrong cause (brief)
        group, code = GENERIC, None
        sentence = t("refusal.generic.sentence")
    title_params = {"as_of": formatting.format_date(corte, region)}
    return RefusalView(
        group=group,
        code=code,
        title=t(f"refusal.group.{group}.title", **title_params),
        sentence=sentence,
        button=_button(group, code, p, latest, region, t),
        lesson=_lesson(group, code, region, t),
        setup_note=t("refusal.group.setup.note") if group == "setup" else None,
        extra=extra,
    )
