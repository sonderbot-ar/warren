import pandas as pd
import sqlite3
from pathlib import Path
from typing import Optional, Dict

from domains.finance.calculations import financial_math as fm 


PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warren_state.db"

def fetch_eav_financial_data(ticker: str) -> pd.DataFrame:
    """
    Connection to SQLite db and retrieves all EAV financial records related to a given ticker
    schema (schemas.py) -> id, ticker, fiscal_year, metric_name, metric_value
    """
    query = "select ticker, fiscal_year, metric_name, metric_value from baseline_financials where ticker = ?"
    with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
        df = pd.read_sql_query(query, conn, params=(ticker,))
    return df

def transform_and_align_financials(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot EAV database rows into a structured time-series matrix for vecotrized math
    """
    if df.empty:
        return pd.DataFrame()

    pivoted_df = df.pivot_table(
        index='fiscal_year',
        columns='metric_name',
        values='metric_value',
        aggfunc='first'
    )

    pivoted_df.index = pd.to_datetime(pivoted_df.index, format='%Y')

    pivoted_df.sort_index(inplace=True)

    return pivoted_df


def compute_financial_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Acts as the orchestrator for the calculation library. 
    Checks if required base metrics exist, then delegates the math to financial_math.py.
    """
    if df.empty:
        return df

    # 1. Profitability & Margins
    if {'revenue', 'cost_of_goods_sold'}.issubset(df.columns):
        df['gross_profit'] = df['revenue'] - df['cost_of_goods_sold']
        df['gross_margin'] = fm.calculate_gross_profit_margin(df['revenue'], df['cost_of_goods_sold'])
        
    if {'revenue', 'gross_profit', 'operating_expenses'}.issubset(df.columns):
        df['operating_income'] = df['gross_profit'] - df['operating_expenses']
        df['operating_margin'] = fm.calculate_operating_profit_margin(df['operating_income'], df['revenue'])

    if {'operating_income', 'tax_expense', 'interest_expense'}.issubset(df.columns):
        df['net_income'] = df['operating_income'] - df['tax_expense'] - df['interest_expense']
        df['net_margin'] = fm.calculate_net_profit_margin(df['net_income'], df['revenue'])

    # 2. Liquidity & Solvency
    if {'current_assets', 'current_liabilities'}.issubset(df.columns):
        df['current_ratio'] = fm.calculate_current_ratio(df['current_assets'], df['current_liabilities'])

    if {'total_debt', 'total_equity'}.issubset(df.columns):
        df['debt_to_equity'] = fm.calculate_debt_to_equity(df['total_debt'], df['total_equity'])

    if {'operating_income', 'interest_expense'}.issubset(df.columns):
        df['interest_coverage'] = fm.calculate_interest_coverage_ratio(df['operating_income'], df['interest_expense'])

    # 3. Efficiency & Returns
    if {'net_income', 'total_assets'}.issubset(df.columns):
        df['roa'] = fm.calculate_roa(df['net_income'], df['total_assets'])

    if {'net_income', 'total_equity'}.issubset(df.columns):
        df['roe'] = fm.calculate_roe(df['net_income'], df['total_equity'])

    # 4. Cash Flows
    if {'operating_cash_flow', 'capital_expenditure'}.issubset(df.columns):
        df['free_cash_flow'] = fm.calculate_free_cash_flow(df['operating_cash_flow'], df['capital_expenditure'])

    return df

def run_valuation_pipeline(ticker: str) -> pd.DataFrame:
    """
    The atomic orchestrator for the quantitative pipeline.
    All qualitative/sentiment capabilities have been stripped to maintain strict separation of concerns.
    """
    raw_eav_data = fetch_eav_financial_data(ticker)
    aligned_data = transform_and_align_financials(raw_eav_data)
    processed_data = compute_financial_metrics(aligned_data)
    
    return processed_data