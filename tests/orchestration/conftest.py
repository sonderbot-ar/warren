"""Test Corp end to end: filings, market data and a week of GDELT news through fake downloaders,
and a fake model that classifies every event and proposes one revenue cut (M7)."""

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from domains.llm.client import FakeClient
from domains.news.gdelt import MasterEntry
from domains.news.store import FILE_URL
from domains.orchestration.nodes import Deps
from domains.orchestration.state import PipelineState
from tests.analysis.conftest import AS_OF, make_db
from tests.fundamentals.conftest import FakeEdgar
from tests.news.test_store import COMPANIES

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
STORY = [  # one story from four outlets, on 2020-06-29 (New York), inside the case window
    ("reuters.com", "Test Corp cuts its revenue outlook on weak demand"),
    ("bloomberg.com", "Test Corp lowers revenue outlook, citing weak demand"),
    ("wsj.com", "Weak demand: Test Corp cuts revenue outlook"),
    ("ft.com", "Test Corp cuts revenue outlook as demand weakens"),
]
SLOTS = [datetime(2020, 6, 29, 15, 0, tzinfo=UTC) + timedelta(minutes=15 * n) for n in range(4)]


def gkg_line(domain: str, url: str, title: str, ts: datetime) -> str:
    cols = [""] * 27
    cols[1], cols[3], cols[4] = ts.strftime("%Y%m%d%H%M%S"), domain, url
    cols[14] = "test corp,1"
    cols[15] = "-2.0,1,2,3,4,5,6"
    cols[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(cols)


def news_files() -> dict[datetime, tuple[MasterEntry, bytes]]:
    out = {}
    for n, (slot, (domain, title)) in enumerate(zip(SLOTS, STORY, strict=True)):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("f.gkg.csv", gkg_line(domain, f"https://{domain}/tst{n}", title,
                                                    slot) + "\n")  # fmt: skip
        content = buffer.getvalue()
        url = FILE_URL.format(ts=slot)
        out[slot] = (MasterEntry(url, len(content), hashlib.md5(content).hexdigest()), content)  # noqa: S324
    return out


def model(system: str, user: str):
    """Classify every headline as about Test Corp; propose one medium revenue cut."""
    if "Forecast, Q1 to Q8" in user:
        return {"proposals": [{"driver": "revenue_growth", "direction": "down", "size": "medium",
                               "duration": "fading", "start_quarter": 1,
                               "rationale": "The company cut its revenue outlook.",
                               "evidence": ["e1"]}],
                "no_material_impact": False, "reason": "An outlook cut."}  # fmt: skip
    ids = re.findall(r"^(h\d+) \|", user, re.MULTILINE)
    return {"event_type": "guidance", "materiality": "high",
            "reasons": ["The company cut its own revenue outlook."],
            "summary": "Test Corp cut its revenue outlook.", "evidence": ids[:1],
            "headlines": [{"id": i, "about": True} for i in ids]}  # fmt: skip


class World:
    """The fakes behind Deps, with counters for what was downloaded or asked."""

    def __init__(self, conn):
        self.conn = conn
        self.files = news_files()
        self.client = FakeClient(model)
        self.master_calls = self.file_calls = self.edgar_calls = 0
        self.now = NOW

    def master(self):
        self.master_calls += 1
        return {slot: entry for slot, (entry, _) in self.files.items()}

    def download(self, url: str) -> bytes:
        self.file_calls += 1
        return next(content for entry, content in self.files.values() if entry.url == url)

    def edgar(self):
        self.edgar_calls += 1
        return FakeEdgar()

    def deps(self) -> Deps:
        return Deps(conn=self.conn, llm=lambda: self.client, edgar=self.edgar,
                    gdelt_master=self.master, gdelt_download=self.download,
                    now=lambda: self.now)  # fmt: skip


@pytest.fixture
def world(db_path):
    conn_cm, conn = make_db(db_path)
    for cik, ticker, names in COMPANIES:  # aliases.csv names every Phase 1 company
        conn.execute("INSERT INTO companies (cik, ticker, name, aliases_json) VALUES (?, ?, ?, ?)",
                     (cik, ticker, names[0], json.dumps(names)))  # fmt: skip
    conn.commit()
    yield World(conn)
    conn_cm.__exit__(None, None, None)


def new_state(**changes) -> PipelineState:
    values = dict(pipeline_id="TST_2020-06-30_p1", ticker="TST", as_of=AS_OF,
                  variants=["named"], review="auto", seed=7, n_samples=200,
                  budget=1_000_000, started_at=NOW)  # fmt: skip
    return PipelineState(**(values | changes))


def register(conn, state: PipelineState) -> None:
    conn.execute(
        "INSERT INTO pipeline_runs (pipeline_id, ticker, as_of, variants, review, seed, "
        "n_samples, status, telemetry_path, code_version) VALUES (?, ?, ?, ?, ?, ?, ?, "
        "'running', 't.jsonl', 'test')",
        (state.pipeline_id, state.ticker, state.as_of.isoformat(), ",".join(state.variants),
         state.review, state.seed, state.n_samples),
    )  # fmt: skip
    conn.commit()
