# warren

A modular engine for fundamental financial analysis. It loads a company's reported fundamentals as they were known on a given date, builds a DCF with explicit, sourced assumptions, and shows how time-shaped news shocks change projected revenue, margins, cash flow and intrinsic value. Warren never predicts stock prices.

## Docs

- [docs/structure-guide.md](docs/structure-guide.md): what Warren is, and every design decision with its status.
- [docs/build-plan.md](docs/build-plan.md): the Phase 1 milestones, their order and their status.
- [CLAUDE.md](CLAUDE.md): working rules for coding assistants.

## Setup

Requires Python 3.11 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in SEC_USER_AGENT
```

## Development

```bash
pytest                  # run the tests
ruff check .            # lint
ruff format .           # format
```

## Fundamentals data (M1)

```bash
python -m domains.fundamentals ingest --all     # download the Phase 1 universe from SEC EDGAR (cached in data/raw/edgar/)
python -m domains.fundamentals report --all     # data-quality reports in data/reports/quality/; exits 1 on any unexplained gap
python -m domains.market load                   # daily prices (Yahoo Finance) and the 10-year Treasury yield (FRED); add --refresh to update
```

Query point-in-time facts with `domains.fundamentals.facts.get_facts(conn, cik, ["revenue"], as_of="2024-06-30", frequency="quarterly")`.

Local data (the SQLite database, logs, raw downloads and reports) lives in `data/`, which is git-ignored.
