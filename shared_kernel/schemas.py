from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class TelemetryEvent(BaseModel):
    """Standardized payload for tracking agent health and token burn"""

    agent_name: str = Field(..., description="Name of node executing the task")
    task_id: str = Field(..., description="Unique identifier for the specific operation")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Time of the event (timezone-aware UTC)",
    )
    tokens_used: int = Field(
        default=0, description="Tracker for amount of tokens used during this operation"
    )
    status: str = Field(..., description="Current state: 'success', 'error', or 'running' ")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Extra content such as: database reference IDs, or error TraceBacks",
    )


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


# PLACEHOLDER: replaced in M7 by typed graph state with small data inline (Decision 2)
class SimulationState(BaseModel):
    """The lightweight payload passed between LangGraph nodes, holding only database pointers."""

    session_id: str = Field(..., description="Unique identifier for this full simulation run")
    current_ticker: str = Field(..., description="The ticker currently being analyzed")
    financial_db_id: str | None = Field(
        default=None, description="SQLite row ID pointing to the baseline financials"
    )
    sentiment_db_ids: list[str] = Field(
        default_factory=list,
        description="List of SQLite row IDs pointing to applied sentiment shocks",
    )
