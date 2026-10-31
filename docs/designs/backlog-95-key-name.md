# Backlog #95: cloud runs read the Anthropic key as WARREN_ANTHROPIC_API_KEY

Issue: https://github.com/sonderbot-ar/warren/issues/95 · Branch `backlog-95-key-name` · Version v0.5.6 when merged.

## Problem

The owner bought API credit and added `ANTHROPIC_API_KEY` to the cloud environment on oct.31.2026. A cloud run started after that does not see it: the cloud environment keeps that name for Claude Code's own sign-in (the settings page warns that it "won't be used to authenticate requests"), so M6 Step 8 still cannot start. The same environment sets `ANTHROPIC_BASE_URL` for Claude Code, and the Anthropic SDK follows that variable by default, so once a key arrived Warren's paid calls would go to Claude Code's endpoint rather than to the public API.

## Plan

**Step 1 (one commit).** `shared_kernel.config.anthropic_api_key` reads `WARREN_ANTHROPIC_API_KEY` first, then `ANTHROPIC_API_KEY`, so a local `.env` keeps working. `config.anthropic_base_url` gives `WARREN_ANTHROPIC_BASE_URL` if set, else `https://api.anthropic.com`; `AnthropicClient` passes it to the SDK, so the ambient `ANTHROPIC_BASE_URL` is never followed. The error for a missing key names both variables and says which to use in the cloud. `.env.example`, the M6 command help and the Build Plan's key table say the same. The key's value is never printed.
Tests: the Warren name wins when both are set, the old name is the fallback, a blank Warren name falls through; the base URL ignores `ANTHROPIC_BASE_URL` and honours the Warren override; the SDK client built by `AnthropicClient` points at the public API (it is built, never called); the missing-key CLI test clears both names. Exit: `pytest`, `ruff check`, `ruff format --check` green.

## Alternatives considered

- *Read the key from a file.* Rejected: the cloud environment's variables are the supported place for secrets, and a file would need its own handling outside the repo.
- *Keep following `ANTHROPIC_BASE_URL`.* Rejected: it is set by the session for Claude Code, not by the owner for Warren, and pointing a paid key at it is at best a confusing failure.

No design decision changes: Decision 1 (keys loaded once, from the environment, behind one config function) holds; only the variable's name gains a Warren-specific form.

## Files

`shared_kernel/config.py`, `domains/llm/client.py`, `domains/llm/__main__.py`, `.env.example`, `tests/shared_kernel/test_config.py`, `tests/llm/test_cli.py`, `docs/build-plan.md`, `docs/designs/m6-llm-steps.md`, `docs/versions.md`.

## Review log

- **Gatekeeper** (NO-GO, 1 blocker, fixed): `test_anthropic_api_key_returns_configured_value` set only the old name, so with `WARREN_ANTHROPIC_API_KEY` in the environment it failed and pytest printed the key. Fixed for every test at once: an autouse fixture in `tests/conftest.py` clears both key names and both base-URL names, so no test can read or print a real key. Taken: the Build Plan's M6 "Before starting" line and the M6 design's Step 8 name the new variable. Confirmed: in anthropic 2.3.0 an explicit `base_url` wins over `ANTHROPIC_BASE_URL`. Not changed: the fallback to `ANTHROPIC_API_KEY` stays, because the cloud keeps that name away from Warren and a local `.env` is the owner's own.

## Where the work stopped

- Done. Merged in #96 (`5b2b1bd`, v0.5.6) after green CI and a gatekeeper GO on re-check (535 tests). Next: the owner renames the cloud variable to `WARREN_ANTHROPIC_API_KEY`; the next run then starts M6 Step 8 with a dry run. After merge the owner renames the cloud variable to `WARREN_ANTHROPIC_API_KEY`, and the next run starts M6 Step 8 with a dry run.
