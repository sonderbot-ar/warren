# Warren classroom prototype

A clickable mock of what Warren should feel like to a finance student and professor at a Latin American university (Structure Guide Decision 11). It is a pitch and a vision guide for the agent teams, not production code: nothing in the engine imports it, and it changes nothing in Phase 1.

- `warren-demo.html`: the whole prototype in one file. Open it in a browser.
- Live copy: https://claude.ai/artifact/BmDReAnFdtA6H5is61nwEs

## The owner's vision (Andrew, oct.30.2026)

- **Users:** students and professors, with a switch between the two views.
- **Excel becomes the explanation, not the engine.** Like paper next to a calculator: every number shows its spreadsheet formula, but tested code does the arithmetic.
- **Every cell is interactive.** Clicking any number opens a side panel with five views:
  1. *Source:* the filing, the XBRL line, the period and the day it became public.
  2. *Formula:* the steps, the numbers, and the same step as a spreadsheet formula.
  3. *Concept:* what the item means (e.g. net debt), with an example from the company.
  4. *What if:* edit the number and see every linked cell in the three statements move, with a reason for each (e.g. more purchases, on credit or in cash: inventory, payables, cash from operations, cash, net debt).
  5. *Read next:* industry headlines public before the analysis date, and related tickers.
- **One of the Phase 1 companies** (Apple here). A toggle between English and Spanish.

## The screens

Assignment, the company (statements with a point-in-time date slider), the valuation (assumptions as sliders, a value range, every projected number opens the panel), what really happened (the forecast scored against the next annual report), and the professor's view of the class.

## What is real and what is not

Apple's figures are its real SEC filings, pulled with Warren's point-in-time layer (`get_facts`, as of 2024-03-31 and 2025-03-31). Receivables, inventory, payables and cash from operations were read from the same filings' company facts; they are not in the Phase 1 concept map yet. Headlines are real events before 31 March 2024, picked by hand. The valuation and what-if math is a simplified JavaScript stand-in; the class, students, Warren baseline figure and professor are examples.
