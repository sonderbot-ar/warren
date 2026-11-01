"""The pipeline's graph state (Decision 2): small, typed data, saved after every node.

Large things stay in the database and are named by id: filings (`financial_facts`), assumptions
(`run_assumptions`), headlines (`article_sightings`). A full state is a few KB. There is no
`current_node`: LangGraph records which node runs next.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Variant = Literal["named", "masked"]
Review = Literal["auto", "manual", "later"]


class SimSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sim_id: str
    p10: float
    p50: float
    p90: float


class PipelineState(BaseModel):
    """One pipeline run for one ticker and as-of date. Each node fills its own fields."""

    model_config = ConfigDict(extra="forbid")

    # the request, fixed when the pipeline starts
    pipeline_id: str
    ticker: str
    as_of: date
    variants: list[Variant]
    review: Review
    seed: int = Field(..., ge=0)
    n_samples: int = Field(..., gt=0)
    budget: int = Field(..., gt=0, description="LLM tokens per LLM node (M6 budget)")
    offline: bool = False
    refresh: bool = False

    # load_fundamentals, load_market
    cik: str | None = None
    company: str | None = None
    ingest_run_id: int | None = None
    market_fetch_ids: dict[str, int] = Field(default_factory=dict)

    # build_baseline
    run_id: str | None = None
    baseline_value_per_share: float | None = None
    baseline_reused: bool | None = None

    # fetch_news, cluster_events
    news_files: dict[str, int] = Field(default_factory=dict, description="files by status")
    articles_kept: int | None = None
    event_run_id: str | None = None
    events_total: int | None = None

    # extract_events, propose_shocks, review_shocks, simulate (by variant)
    classified: dict[str, dict[str, int]] = Field(default_factory=dict)
    proposal_set: dict[str, int | None] = Field(default_factory=dict)
    proposals: dict[str, list[str]] = Field(default_factory=dict, description="in words")
    reviewed: dict[str, dict[str, int]] = Field(default_factory=dict)
    sim: dict[str, SimSummary | None] = Field(default_factory=dict)

    # write_report
    report_path: str | None = None

    @property
    def case_id(self) -> str:
        """M6 keys its answers by `<TICKER>_<as-of>`, as every eval case id is built."""
        return f"{self.ticker}_{self.as_of.isoformat()}"
