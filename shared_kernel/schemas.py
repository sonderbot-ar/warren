from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMUsage(BaseModel):
    """One model's calls in one node: every attempt, as `llm_calls` records it (M6)."""

    model_config = ConfigDict(extra="forbid")

    model: str
    calls: int = Field(..., ge=0, description="attempts, valid or not")
    invalid: int = Field(default=0, ge=0, description="attempts refused or failed")
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)


class TelemetryEvent(BaseModel):
    """One JSON line of a pipeline's telemetry (Decision 5, settled in M7): a node starting or
    ending, with its timing, status, error and, for LLM nodes, model and tokens."""

    model_config = ConfigDict(extra="forbid")

    pipeline_id: str = Field(..., description="the pipeline run")
    node: str = Field(..., description="the graph node")
    status: Literal["started", "ok", "error", "interrupted"]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Time of the event (timezone-aware UTC)",
    )
    duration_ms: int | None = Field(default=None, ge=0, description="on end lines")
    error: str | None = Field(default=None, description="type and message, never a traceback")
    llm: list[LLMUsage] = Field(default_factory=list, description="LLM nodes, per model")


# PLACEHOLDER: replaced in M2 by a multi-year view built from financial_facts (Decision 4)
class BaselineFinancials(BaseModel):
    """Standardized blueprint for quantitative data extracted from APIs or Filings"""

    ticker: str = Field(..., description="The stock ticker symbol (e.g., 'AAPL')")
    fiscal_year: int = Field(..., description="The year the data represents")
    revenue: float = Field(..., description="Total revenue in absolute numbers")
    cost_of_goods_sold: float = Field(..., description="Total COGS in absolute numbers")
    # MUST be computed, never assumed
    # operating_expenses: float = Field(..., description="Total operating expenses in absolute numbers")  # noqa: E501
    # discount_rate: float = Field(default=0.10, description="Weighted Average Cost of Capital (WACC)")  # noqa: E501

    # MUST be computed or asked, never assumed
    # terminal_growth_rate: float = Field(default=0.02, description="Assumed perpetual growth rate for DCF")  # noqa: E501


# PLACEHOLDER: replaced in M4 by the time-shaped, probabilistic Shock schema (Decision 6)
class SentimentShock(BaseModel):
    """Translates qualitative NLP analysis into quantitative simulation parameters"""

    source_id: str = Field(
        ..., description="Database reference ID to the parsed news or academic article"
    )
    sentiment_score: float = Field(
        ..., ge=-1.0, le=1.0, description="Normalized score from -1.0 (negative) to 1.0 (positive)"
    )
    revenue_modifier: float = Field(
        default=0.0, description="Percentage impact on baseline revenue (e.g., -0.05 for a 5% drop)"
    )
    cost_modifier: float = Field(default=0.0, description="Percentage impact on baseline costs")
    rationale: str = Field(
        ..., description="The agent's brief justification for these specific modifiers"
    )
