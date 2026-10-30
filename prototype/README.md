# Warren classroom prototype

A clickable mock of what Warren should feel like to a finance student and professor at a Latin American university (Structure Guide Decision 11). It is a pitch and a vision guide for the agent teams, not production code: nothing in the engine imports it, and it changes nothing in Phase 1.

- `warren-demo.html`: the whole prototype in one file. Open it in a browser.
- Live copy: https://claude.ai/artifact/BmDReAnFdtA6H5is61nwEs

The five screens: assignment, the company (click any number to see its filing; move the date to hide what was not public yet), the valuation (assumptions as sliders, a value range, every projected number explains itself), what really happened (the forecast scored against the next annual report), and the professor's view of the class.

Company figures are The Coca-Cola Company's real 10-K data, pulled with Warren's point-in-time layer (`get_facts`, as of 2023-03-31, 2024-03-31 and 2025-03-31). The valuation math in the page is a simplified JavaScript stand-in; the class, students, Warren baseline figure and the professor are examples.
