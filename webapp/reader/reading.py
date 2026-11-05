"""What the question reader returns, and the code check every reading passes before it is shown.

Decision 9 (nov.03.2026 and nov.04.2026) and the brief's sorting rule (`docs/product/brief.md`,
section 2): the reader only labels a question. It returns the kind, the companies, the date and
the model inputs the question names, with a value only when it is copied word for word from the
question. It never returns a financial number. Code checks every field here; a field that fails
is dropped and the reading is marked unsure, so the reading card asks the student instead of
guessing. The student confirms or fixes the reading before anything is computed.

This module has no words a student reads: the reading card's text lives in the catalogues.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from functools import cache
from pathlib import Path

from domains.analysis import dcf

# The four kinds of the brief (§2), plus questions Warren declines (§4).
KINDS = ("dato", "estimacion", "cambio_de_supuesto", "evento", "fuera_de_alcance")

# Why a question is out of scope (brief §4). Concepts go to the side panel's Concepto tab;
# sin_pregunta is a message with nothing Warren can read ("ayuda con mi tp").
OUT_OF_SCOPE = ("precio_o_consejo", "otra_empresa", "concepto", "sin_pregunta")

# The model inputs a student can name (brief §2, "Model inputs"): the engine's drivers and single
# values, less the two that are never inputs (the market value of equity comes from the price,
# and the roll-forward years are bookkeeping), plus the two teaching overrides.
NEVER_INPUTS = ("equity_market_value", "roll_years")
TEACHING_OVERRIDES = ("wacc", "terminal_method")
INPUTS = (
    tuple(dcf.DRIVERS)
    + tuple(name for name in dcf.SINGLE_VALUES if name not in NEVER_INPUTS)
    + TEACHING_OVERRIDES
)

# The list of transmissions (brief §2): an event that reaches a model input by a listed, sourced
# route. Its first and only entry, proposed in backlog #143, moves the risk-free rate.
TRANSMISSIONS = {"fed_policy_surprise": "risk_free"}

HOWS = ("set", "add", "scale")  # a level, a move in its own unit, a proportional move
DIRECTIONS = ("up", "down")

UNIVERSE_CSV = Path(__file__).resolve().parents[2] / "domains" / "fundamentals" / "universe.csv"


@cache
def tickers() -> tuple[str, ...]:
    """The Phase 1 universe, read from the engine's own list (never a copy of it)."""
    with UNIVERSE_CSV.open(encoding="utf-8", newline="") as handle:
        return tuple(row["ticker"] for row in csv.DictReader(handle))


@dataclass(frozen=True)
class NamedInput:
    """One model input the question changes or names.

    `how` is "set" (a new level: "si la beta fuera 1,2"), "add" (a move in the input's own unit:
    "baja un punto") or "scale" (a proportional move: "aumenta el capex un 20%", "doubled");
    `direction` says up or down when the question does; `value_text` is the number and its unit
    copied word for word from the question ("25 puntos básicos"), or None when the question
    gives none; `via` names a transmission when the question reaches the input through one.

    With `via`, `value_text` is the size of the event the student names ("la Fed sube 25 puntos
    básicos"), never the input's change: the transmission's sourced range turns the one into the
    other (backlog #143; about a third of a basis point on the 10-year per basis point of
    surprise, Kuttner 2001). The card shows it as the event's size. Moving the input one for one
    would quietly turn an event into an input, which the brief forbids (§2).
    """

    name: str
    how: str | None = None
    direction: str | None = None
    value_text: str | None = None
    via: str | None = None


@dataclass(frozen=True)
class Reading:
    """The reader's labels for one question. Never a financial number."""

    kind: str
    companies: tuple[str, ...] = ()
    as_of: str | None = None  # an ISO date, only when the question sets an absolute one
    period: str | None = None  # the date or period named, copied word for word
    inputs: tuple[NamedInput, ...] = ()
    out_of_scope: str | None = None
    unsure: bool = False
    dropped: tuple[str, ...] = field(default=(), compare=False)  # fields the check removed

    @classmethod
    def from_dict(cls, data: dict) -> Reading:
        """Build a reading from the reader's JSON. Unknown or malformed parts become a dropped
        field, never an exception, so a bad answer from a model is just an unsure reading."""
        dropped: list[str] = []
        kind = data.get("kind")
        if not isinstance(kind, str):
            kind, dropped = "", ["kind"]
        companies = data.get("companies") or []
        if not isinstance(companies, list) or not all(isinstance(c, str) for c in companies):
            companies, dropped = [], [*dropped, "companies"]
        inputs: list[NamedInput] = []
        raw_inputs = data.get("inputs") or []
        if not isinstance(raw_inputs, list):
            raw_inputs, dropped = [], [*dropped, "inputs"]
        for item in raw_inputs:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                dropped.append("inputs")
                continue
            parts = {k: item.get(k) for k in ("how", "direction", "value_text", "via")}
            if any(v is not None and not isinstance(v, str) for v in parts.values()):
                dropped.append("inputs")
                continue
            inputs.append(NamedInput(name=item["name"], **parts))
        text_fields = {}
        for name in ("as_of", "period", "out_of_scope"):
            value = data.get(name)
            if value is not None and not isinstance(value, str):
                value, dropped = None, [*dropped, name]
            text_fields[name] = value
        return cls(
            kind=kind,
            companies=tuple(companies),
            inputs=tuple(inputs),
            unsure=bool(data.get("unsure", False)) or bool(dropped),
            dropped=tuple(dropped),
            **text_fields,
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "companies": list(self.companies),
            "as_of": self.as_of,
            "period": self.period,
            "inputs": [asdict(i) for i in self.inputs],
            "out_of_scope": self.out_of_scope,
            "unsure": self.unsure,
        }


_STOPWORDS = frozenset(
    "a al de del el en la las lo los su sus por para the of in its at on for by as".split()
)


def normalise(text: str) -> str:
    """Lower case, no accents, no punctuation apart from inside numbers, no filler words.
    Used to find a copied span in the question and to compare spans when scoring."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^\w\s%$.,]", " ", folded)
    folded = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", folded)
    return " ".join(w for w in folded.split() if w not in _STOPWORDS)


def copied_from(span: str, question: str) -> bool:
    """True when `span` appears in the question, word for word up to case, accents and
    punctuation (Decision 9: a value is filled in only when copied from the question)."""
    wanted = normalise(span)
    return bool(wanted) and f" {wanted} " in f" {normalise(question)} "


def check(reading: Reading, question: str, today: date) -> Reading:
    """The code check of Decision 9. Every field outside the vocabularies, every value or
    period not copied from the question, and every date after `today` (the last ended day) is
    dropped, and the reading is then unsure. Kind-dependent rules keep the reading coherent:
    only a cambio de supuesto changes inputs, and only fuera_de_alcance has a reason."""
    dropped = list(reading.dropped)
    kind = reading.kind
    if kind not in KINDS:
        kind, dropped = "", [*dropped, "kind"]

    companies = tuple(sorted({c for c in reading.companies if c in tickers()}))
    if len(companies) != len(set(reading.companies)):
        dropped.append("companies")

    as_of = reading.as_of
    if as_of is not None:
        try:
            parsed = date.fromisoformat(as_of)
        except ValueError:
            parsed = None
        if parsed is None or parsed > today or len(as_of) != 10:
            as_of, dropped = None, [*dropped, "as_of"]

    period = reading.period
    if period is not None and not copied_from(period, question):
        period, dropped = None, [*dropped, "period"]
    if as_of is not None and period is None:  # a fecha de corte the question never states
        as_of, dropped = None, [*dropped, "as_of"]

    inputs = []
    for item in reading.inputs:
        if item.name not in INPUTS:
            dropped.append("inputs")
            continue
        if item.how not in (None, *HOWS) or item.direction not in (None, *DIRECTIONS):
            dropped.append("inputs")
            continue
        if item.via is not None and TRANSMISSIONS.get(item.via) != item.name:
            dropped.append("inputs")
            continue
        if item.how == "set" and item.direction is not None:  # the level already says it
            item = replace(item, direction=None)
        if item.value_text is not None and not copied_from(item.value_text, question):
            item, dropped = replace(item, value_text=None), [*dropped, "inputs.value_text"]
        inputs.append(item)
    if kind != "cambio_de_supuesto" and inputs:
        inputs, dropped = [], [*dropped, "inputs"]

    out_of_scope = reading.out_of_scope
    if kind == "fuera_de_alcance":
        if out_of_scope not in OUT_OF_SCOPE:
            out_of_scope, dropped = None, [*dropped, "out_of_scope"]
    elif out_of_scope is not None:
        out_of_scope, dropped = None, [*dropped, "out_of_scope"]

    return Reading(
        kind=kind,
        companies=companies,
        as_of=as_of,
        period=period,
        inputs=tuple(sorted(inputs, key=lambda i: (i.name, i.via or ""))),
        out_of_scope=out_of_scope,
        unsure=reading.unsure or bool(dropped),
        dropped=tuple(dict.fromkeys(dropped)),
    )
