"""The question reader's instructions to the model, and the shape its answer must take.

F2 Step 3, part 2 (`docs/designs/f2-web-app.md`). The instructions restate the brief's sorting
rule (`docs/product/brief.md`, section 2) and the labelling rules of Step 3's results, part 1,
so the model labels a question the way the labelled set does. They are built from the same
vocabularies the code check uses (`reading.py`), so a name the prompt offers is always a name
the check accepts.

The worked examples are written for the prompt and quote none of the labelled set's questions,
nor any run of five of their words (tested in `tests/webapp/test_reader_model.py`): the set is
the reader's exam, and an exam that leaks into the instructions measures nothing (Dwork et al.
2015 on reusing a holdout).

This is model input, not text a student reads, so it stays in English and outside the
catalogues; the model answers questions in any language.
"""

from __future__ import annotations

import json

from webapp.reader.reading import (
    DIRECTIONS,
    HOWS,
    INPUTS,
    KINDS,
    OUT_OF_SCOPE,
    TRANSMISSIONS,
    tickers,
)

# How students name the companies (the universe's tickers come from the engine's own list; these
# are only the names a student types). Look-alikes that are other companies are listed apart.
COMPANY_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "WMT": "Walmart (Walmart Inc., the US parent)",
    "KO": "Coca-Cola, The Coca-Cola Company, Coke",
    "PG": "Procter & Gamble, P&G",
    "JNJ": "Johnson & Johnson, J&J",
    "CAT": "Caterpillar",
    "XOM": "ExxonMobil, Exxon",
}
OTHER_COMPANIES = (
    "Walmex (Walmart de México), Coca-Cola FEMSA (KOF), FEMSA, and any company not listed above"
)

INPUT_MEANINGS = {
    "revenue_growth": "growth of sales or revenue (ventas, ingresos)",
    "operating_margin": "operating or EBIT margin (margen operativo)",
    "tax_rate": "the company's tax rate (tasa de impuestos)",
    "da_pct": "depreciation and amortisation as a share of revenue",
    "capex_pct": "capital spending, capex, as a share of revenue (inversión)",
    "nwc_pct": "net working capital as a share of revenue (capital de trabajo)",
    "risk_free": "the risk-free rate, the 10-year Treasury yield (tasa libre de riesgo)",
    "beta": "the stock's beta",
    "erp": "the equity risk premium (prima de riesgo de mercado)",
    "cost_of_debt": "the cost of debt (costo de la deuda)",
    "debt_tax_rate": "the tax rate on interest, the tax shield's rate",
    "debt": "the amount of debt (deuda)",
    "cash_and_investments": "cash and investments (caja, efectivo)",
    "minority_interest": "minority or non-controlling interest",
    "shares": "the number of shares (acciones en circulación)",
    "terminal_growth": "growth in perpetuity after the forecast (crecimiento terminal, g)",
    "wacc": "the discount rate itself, WACC (costo de capital), set directly",
    "terminal_method": "how the terminal value is computed (Gordon, a multiple)",
}


def answer_schema() -> dict:
    """The JSON schema the runtime holds the model's answer to. It allows only the
    vocabularies; the code check still checks every field (Decision 9)."""
    nullable = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "out_of_scope": {"type": ["string", "null"], "enum": [*OUT_OF_SCOPE, None]},
            "companies": {"type": "array", "items": {"type": "string", "enum": list(tickers())}},
            "period": nullable,
            "as_of": nullable,
            "inputs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": list(INPUTS)},
                        "how": {"type": ["string", "null"], "enum": [*HOWS, None]},
                        "direction": {"type": ["string", "null"], "enum": [*DIRECTIONS, None]},
                        "value_text": nullable,
                        "via": {"type": ["string", "null"], "enum": [*TRANSMISSIONS, None]},
                    },
                    "required": ["name", "how", "direction", "value_text", "via"],
                },
            },
            "unsure": {"type": "boolean"},
        },
        "required": ["kind", "out_of_scope", "companies", "period", "as_of", "inputs", "unsure"],
    }


# Worked examples: question, then the answer. None of these is in the labelled set.
EXAMPLES: tuple[tuple[str, dict], ...] = (
    (
        "¿Qué capex reportó Caterpillar en 2022?",
        {"kind": "dato", "companies": ["CAT"], "period": "2022"},
    ),
    (
        "What would a DCF say Johnson & Johnson is worth per share?",
        {"kind": "estimacion", "companies": ["JNJ"]},
    ),
    (
        "Con datos hasta el 30 de junio de 2023, ¿qué ingresos proyectaba Warren para Exxon?",
        {
            "kind": "estimacion",
            "companies": ["XOM"],
            "period": "30 de junio de 2023",
            "as_of": "2023-06-30",
        },
    ),
    (
        "Si la prima de riesgo de mercado de P&G pasa a 6%, ¿cuánto cambia su valor?",
        {
            "kind": "cambio_de_supuesto",
            "companies": ["PG"],
            "inputs": [{"name": "erp", "how": "set", "value_text": "6%"}],
        },
    ),
    (
        "What if Caterpillar's capex were cut by a third?",
        {
            "kind": "cambio_de_supuesto",
            "companies": ["CAT"],
            "inputs": [
                {"name": "capex_pct", "how": "scale", "direction": "down", "value_text": "a third"}
            ],
        },
    ),
    (
        "Si la Reserva Federal recorta 50 puntos básicos por sorpresa, ¿qué le pasa al valor de "
        "Walmart?",
        {
            "kind": "cambio_de_supuesto",
            "companies": ["WMT"],
            "inputs": [
                {
                    "name": "risk_free",
                    "how": "add",
                    "direction": "down",
                    "value_text": "50 puntos básicos",
                    "via": "fed_policy_surprise",
                }
            ],
        },
    ),
    (
        "¿Cómo afectaría a Johnson & Johnson una guerra comercial con China?",
        {"kind": "evento", "companies": ["JNJ"]},
    ),
    (
        "Should I buy Exxon shares this week?",
        {"kind": "fuera_de_alcance", "out_of_scope": "precio_o_consejo", "companies": ["XOM"]},
    ),
    (
        "¿Qué es el capital de trabajo neto?",
        {"kind": "fuera_de_alcance", "out_of_scope": "concepto"},
    ),
)

RULES = """\
You read one question from a finance student (Spanish or English, often with typos, no accents,
slang, tickers or nicknames) and label it. You never compute, estimate or invent a number: you
only copy words from the question. Answer with the JSON object only.

KINDS (pick exactly one, in this order of precedence):
- "cambio_de_supuesto": the student changes one or more model inputs (listed below), with or
  without a value ("si el beta fuera 1,1", "if margins fall two points", "con un WACC de 9%").
  Every change asked for must be a model input. If the student turns an event into an input
  change themselves ("if there is a recession and the margin drops a point"), it is still a
  cambio: label the input. A question that asks for a filed figure and a change together is a
  cambio.
- "evento": the question names an event and no input change: an election, a war, a tariff, a
  recession, a strike, a merger, a buyback or new borrowing with no input named, a vague
  "what if things go badly", "growth slows" without saying which growth, or a follow-up that
  names nothing readable on its own ("and for Microsoft?", "y si fuera 3%?"). Events get no
  inputs.
- "dato": a figure or ratio the company filed (sales, net income, margins, debt, cash, capex,
  growth already reported) for a reported period or a reported trend.
- "estimacion": an output of Warren's model: the DCF value, a forecast for periods not yet
  reported, the forecast's range or error, the model's track record, a default sensitivity
  table, the assumptions the model uses.
- "fuera_de_alcance": Warren does not answer it. Set out_of_scope to:
  "precio_o_consejo" for stock prices, price targets, buy/sell/hold advice, returns on the
  stock, or trading multiples ("at how many times EBITDA does it trade") - this reason wins
  over the others; "otra_empresa" when the company is not in the list below; "concepto" for a
  definition or a textbook concept with no company ("what is beta"); "sin_pregunta" when there
  is no question Warren can read ("help with my homework").
out_of_scope is null for every other kind.

COMPANIES: list the tickers of the companies named, from this list only:
{companies}
Other companies, including {others}, are never mapped to a ticker: a question about only those
is fuera_de_alcance with "otra_empresa". Keep listed companies even when the question is out of
scope. Use [] when none is named.

PERIOD: any date or period the question names, copied exactly as written ("2023", "3T24",
"last quarter", "últimos cinco años", "a fines de 2024"). null when none. An out-of-scope
question keeps no period and no as_of.

AS_OF (the "fecha de corte"): an ISO date YYYY-MM-DD, only when the question asks for a model
output or a change as of a past date ("con lo que se sabía al 31/03/2024", "as of the end of
2022" is 2022-12-31; the end of a quarter is its last day). Day-first dates are read
day-first in Spanish. A filed figure's period is a period, never an as_of. "Today", "now",
"hoy" and "in the past" are neither. Otherwise null.

INPUTS (only for cambio_de_supuesto; [] for every other kind). Names:
{inputs}
For each input:
- how: "set" for a new level ("a 15%", "from 18% to 21%", "were 1.2"); "add" for a move in the
  input's own unit ("sube 50 pb", "drops two points"); "scale" for a proportional move ("un
  20% más", "doubled", "by half"); null when the question gives no size.
- direction: "up" or "down" with add, scale or no value; null with set.
- value_text: the number and its unit copied word for word ("25 puntos básicos", "1,2",
  "7.5%", "half a point", "Gordon"); nothing else. null when there is no value in the
  question or it is in another unit than the input's.
- via: "fed_policy_surprise" only when the Federal Reserve's rate move is how the question
  reaches an input; then name "risk_free", and value_text is the size of the Fed's move as
  written. A Fed move with no word "surprise" is read the same way. Otherwise null.
The student who changes the share count names "shares"; the student who names the discount
rate itself names "wacc".

UNSURE: true when you cannot tell the kind, the company or the input with confidence. A wrong
label with unsure false is the worst answer you can give; an unsure label sends the student to
a short menu. Be sure on clear questions.
"""


def _example_answer(partial: dict) -> dict:
    inputs = [
        {"how": None, "direction": None, "value_text": None, "via": None, **item}
        for item in partial.get("inputs", [])
    ]
    return {
        "kind": partial["kind"],
        "out_of_scope": partial.get("out_of_scope"),
        "companies": partial.get("companies", []),
        "period": partial.get("period"),
        "as_of": partial.get("as_of"),
        "inputs": inputs,
        "unsure": False,
    }


def system_prompt() -> str:
    companies = "\n".join(f"- {t}: {COMPANY_NAMES[t]}" for t in tickers())
    inputs = "\n".join(f"- {name}: {INPUT_MEANINGS[name]}" for name in INPUTS)
    examples = "\n".join(
        f"Question: {question}\nAnswer: {json.dumps(_example_answer(answer), ensure_ascii=False)}"
        for question, answer in EXAMPLES
    )
    return (
        RULES.format(companies=companies, others=OTHER_COMPANIES, inputs=inputs)
        + "\nEXAMPLES:\n"
        + examples
        + "\n"
    )


def user_message(question: str) -> str:
    return f"Question: {question}\nAnswer:"
