"""Warren's entry point: one command runs the whole pipeline for a company and a date (M7).

    python main.py run --ticker MSFT --as-of 2022-06-02

See `domains/orchestration/__main__.py` for every command; this file only calls it
(Decision 11, guardrail 4: the engine is a library, the command line calls it).
"""

import sys

from domains.orchestration.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
