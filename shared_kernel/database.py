import sqlite3
import uuid
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

from shared_kernel.schemas import BaselineFinancials, SentimentShock

# absolute path to data folder
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warren_state.db"

@contextmanager
def get_db_connection():
    """Atomic context manager that insures a connection is SAFELY closed even if an agent crashes"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=10.0) #check unit
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# The initial elements in this DB will of course be UPDATED WHEN deemed necessary


