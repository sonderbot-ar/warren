"""The question in front of the answer (F2 Step 4b, part 3a): read, confirm, then compute.

A student types a question on *Inicio*. The reader (Claude Haiku behind the card, Decision 9)
labels it; the code check (`reader.reading.check`) and the card's rules (`reader.card.card_for`)
turn the labels into a reading card. The student confirms it, answers its asks or corrects it
with the menus, and only then does Warren compute. Nothing here computes a financial number,
and this module holds no words a student reads: every text is a catalogue key.

What the student chose wins over what the reader read. Choices come in the address, so every
state of the card is a link that works without JavaScript and can be shared:

- `empresa`: the company, from the card's company buttons or the menus;
- `tipo`: the kind of question, from the menus;
- `fecha`: the *fecha de corte*, from the menus (never after the last ended day);
- `corregido=1`: the student sent the menus, so the reading is theirs and no longer unsure.

The first screen answers one question (brief Q5): an *estimación* of one company's revenue for
the next four quarters. Every other kind is read and confirmed, then told that its screen comes
later; the reading is never stretched to fit the one screen that exists.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from threading import Lock

from webapp.formatting import Region, format_date
from webapp.reader.card import Card, Item, card_for
from webapp.reader.reading import KINDS, Reading, check, tickers

# The longest question the reader is sent. Longer text is cut here, never sent whole: a
# question is a sentence or two, and the reader is paid per token (the owner's card, nov.08.2026).
MAX_QUESTION = 400

# The kinds a student can pick in the menus: the brief's four (§2). Out of scope is never picked.
MENU_KINDS = tuple(k for k in KINDS if k != "fuera_de_alcance")

# The one screen built so far, by kind: brief Q5 (revenue, next four quarters) for an estimación.
SCREENS = {"estimacion": "respuesta"}

# What the card leads to (the template shows one block per step).
STEP_CALCULATE = "calcular"  # ready, and a screen exists: the Calcular button
STEP_ASK = "preguntar"  # something to answer first: no Calcular
STEP_LATER = "pronto"  # confirmed, but this kind's screen is not built yet
STEP_OUT = "fuera"  # out of scope: the card says what Warren does instead


@dataclass(frozen=True)
class Choices:
    """What the student chose in the address. None where they chose nothing."""

    empresa: str | None = None
    tipo: str | None = None
    fecha: date | None = None
    corregido: bool = False

    @classmethod
    def from_query(cls, query, latest: date) -> Choices:
        """Read the address's choices; anything unknown is ignored, never an error, so a stale
        or edited link still gives a card (the reader's own reading, with the menus)."""
        empresa = (query.get("empresa") or "").upper() or None
        if empresa not in tickers():
            empresa = None
        tipo = query.get("tipo") or None
        if tipo not in MENU_KINDS:
            tipo = None
        fecha = None
        raw = query.get("fecha")
        if raw:
            try:
                fecha = date.fromisoformat(raw)
            except ValueError:
                fecha = None
            if fecha is not None and fecha > latest:  # nothing from the future
                fecha = None
        return cls(empresa, tipo, fecha, query.get("corregido") == "1")

    def params(self) -> dict[str, str]:
        """The choices as address parameters, for the next link."""
        out = {}
        if self.empresa:
            out["empresa"] = self.empresa
        if self.tipo:
            out["tipo"] = self.tipo
        if self.fecha:
            out["fecha"] = self.fecha.isoformat()
        if self.corregido:
            out["corregido"] = "1"
        return out


def clean_question(text: str | None) -> str:
    """The question as the reader gets it: spaces collapsed, at most MAX_QUESTION characters."""
    return " ".join((text or "").split())[:MAX_QUESTION]


def apply_choices(reading: Reading, choices: Choices) -> Reading:
    """The reading with the student's choices in place of the reader's.

    A company or a kind the student picked replaces the reader's. A date picked in the menus is
    the fecha de corte. When the student sent the menus (`corregido`), every field on the card
    is theirs, so the reading is no longer unsure and the reader's dropped fields are forgotten.
    Picking a kind other than a cambio de supuesto drops the inputs, as the code check does.
    """
    out = reading
    if choices.tipo is not None:
        out = replace(out, kind=choices.tipo, out_of_scope=None)
        if choices.tipo != "cambio_de_supuesto":
            out = replace(out, inputs=())
    if choices.empresa is not None:
        out = replace(out, companies=(choices.empresa,))
    if choices.fecha is not None:
        out = replace(out, as_of=choices.fecha.isoformat())
    if choices.corregido:
        out = replace(out, unsure=False, dropped=())
    return out


@dataclass(frozen=True)
class QuestionCard:
    """The card for one question: the engine's card, the step it leads to, and the fecha de
    corte an answer would use."""

    question: str
    card: Card
    step: str
    corte: date
    extra_asks: tuple[Item, ...]  # asks the screen adds to the card's own (one company)

    @property
    def reading(self) -> Reading:
        return self.card.reading

    @property
    def asks(self) -> tuple[Item, ...]:
        return self.card.asks + self.extra_asks

    @property
    def company(self) -> str | None:
        companies = self.reading.companies
        return companies[0] if len(companies) == 1 else None

    @property
    def show_menus(self) -> bool:
        """The menus open by themselves when the reader was unsure or could not read (Decision 9's
        fallback); otherwise they are one click away (Corregir)."""
        return self.reading.unsure


def question_card(
    question: str,
    reading: Reading,
    choices: Choices,
    latest: date,
    region: Region,
) -> QuestionCard:
    """The card a student sees for a checked reading and their choices. `latest` is the last
    ended day in New York, the default fecha de corte."""
    reading = apply_choices(reading, choices)
    card = card_for(reading, question, latest, region)
    if choices.fecha is not None:  # the date came from the menus, not the question: say so
        notes = tuple(
            Item("corte_chosen", {"date": format_date(choices.fecha, region)})
            if note.code == "corte_from_question"
            else note
            for note in card.notes
        )
        card = replace(card, notes=notes)
    corte = date.fromisoformat(reading.as_of) if reading.as_of else latest

    extra: list[Item] = []
    if reading.kind in SCREENS and len(reading.companies) > 1:
        # one company per answer on this screen: the student picks which, from the ones read
        extra.append(Item("one_company", {"companies": list(reading.companies)}))

    if reading.kind == "fuera_de_alcance":
        step = STEP_OUT
    elif card.asks or extra:
        step = STEP_ASK
    elif reading.kind in SCREENS:
        step = STEP_CALCULATE
    else:
        step = STEP_LATER
    return QuestionCard(question, card, step, corte, tuple(extra))


def item_params(item: Item, t: Callable[..., str], region: Region) -> dict[str, str]:
    """An ask's or note's params as words for its catalogue text: an input's name in the
    student's language, a list of companies by name, a number in the region's format."""
    from babel.numbers import format_decimal

    out = {}
    for key, value in item.params.items():
        if key == "input":
            out[key] = t(f"input.{value}")
        elif key == "companies":
            out[key] = ", ".join(t(f"company.{c}") for c in value)
        elif isinstance(value, Decimal):
            out[key] = format_decimal(value, locale=region.babel)
        elif isinstance(value, list):
            out[key] = ", ".join(str(v) for v in value)
        else:
            out[key] = str(value)
    return out


def ask_key(item: Item) -> str:
    """The catalogue key of an ask: the card's own under "card.ask.", the screen's under
    "question.ask."."""
    return f"question.ask.{item.code}" if item.code == "one_company" else f"card.ask.{item.code}"


def note_key(item: Item) -> str:
    return f"question.note.{item.code}" if item.code == "corte_chosen" else f"card.note.{item.code}"


def today_after(latest: date) -> date:
    """Today in New York: the day after the last ended one (`shared_kernel.calendar`)."""
    return latest + timedelta(days=1)


class Reader:
    """The question reader behind the card, with the answers it already gave kept in memory.

    `read(text, latest)` returns the checked reading. The same question on the same day is read
    once: a reading never changes within a day (the check bounds dates by the last ended day),
    and every new reading is a paid call (the owner's card, nov.08.2026). `backend_factory`
    makes the model's backend on first use; when it cannot (no key, no network), the reader is
    unavailable and every card opens its menus, as Decision 9 says.
    """

    def __init__(self, backend_factory: Callable[[], object] | None, size: int = 512):
        self._factory = backend_factory
        self._backend = None
        self._failed = backend_factory is None
        self._kept: OrderedDict[tuple[str, date], Reading] = OrderedDict()
        self._size = size
        self._lock = Lock()

    def _get_backend(self):
        with self._lock:
            if self._backend is None and not self._failed:
                try:
                    self._backend = self._factory()
                except Exception:  # no key, no SDK: the menus, never a crash on a page
                    self._failed = True
            return self._backend

    def read(self, text: str, latest: date) -> Reading:
        from webapp.reader.model import read_question, unavailable

        key = (text, latest)
        with self._lock:
            if key in self._kept:
                self._kept.move_to_end(key)
                return self._kept[key]
        backend = self._get_backend()
        if backend is None:
            return unavailable()
        reading = read_question(text, latest, backend)
        if "reader" not in reading.dropped:  # an unavailable reader is tried again next time
            with self._lock:
                self._kept[key] = reading
                while len(self._kept) > self._size:
                    self._kept.popitem(last=False)
        return reading


def fixed_reader(readings: dict[str, Reading]) -> Callable[[str, date], Reading]:
    """A reader for tests and screenshots: known questions get their stored reading, passed
    through the same code check; anything else is unavailable."""
    from webapp.reader.model import unavailable

    def read(text: str, latest: date) -> Reading:
        if text not in readings:
            return unavailable()
        return check(readings[text], text, latest)

    return read
