---
name: "warren-scout"
description: "Run Warren's research scouts: find open-source repos and Hugging Face models that could help the next milestones, judge them on paper, and file the approved ones as backlog issues in sonderbot-ar/warren."
---

# Warren research scouts

Many open-source projects and open models could save Warren work or money (Structure Guide Decision 12). Scouts look for them, the existing Goldfish reviewers judge them on paper, and approved ones become ordinary `backlog` issues that an Elephant picks up like any other. Scouts never change the code.

## When

- **Kickoff (once):** four scouts in parallel, one per lane below.
- **Routine:** one scout every 3 days, on a scheduled run. It takes the lane whose next milestone is soonest in `docs/build-plan.md`, and rotates to the next lane if the last two runs found nothing new there.
- Skip a routine run when 10 or more `scout` issues are still waiting for a verdict.

## Lanes

1. **Data:** data sources and loaders (SEC EDGAR and XBRL tooling, prices, rates, IFRS filings for Decision 11).
2. **Valuation:** finance math, DCF, Monte Carlo, forecast evaluation and test tooling.
3. **News models:** GDELT tooling, and open models on Hugging Face for event extraction, company matching and classification (M5, M6). Each model notes whether it runs on the owner's machine (below).
4. **Agent tooling:** orchestration and telemetry (M7), and anything that makes the agent team cheaper.

## The owner's machine

Warren runs locally on an Apple M5 MacBook with 16 GB of unified memory. A model must run there with room left for Warren itself: about 8 billion parameters at most when quantized to 4 bits (about 5 GB of memory), smaller when it runs at full precision. Prefer models with a Metal or MLX build (`mlx-community` on Hugging Face, `llama.cpp` or Ollama GGUF, or PyTorch with the `mps` backend). A model that needs an NVIDIA GPU (CUDA only) fails. Libraries must install on macOS with Apple Silicon (arm64).

## The run lead (the session running this skill)

1. Read `CLAUDE.md`, `docs/build-plan.md` (Section 2 and the next milestones), `docs/structure-guide.md` Decisions 8, 9, 11 and 12, and the open and closed issues labelled `scout`.
2. Write each scout a brief: its lane, the two or three concrete needs from the build plan it should look for, the candidates already filed (so it skips them), and how many to return.
3. Run the `scout` agent once per lane (in parallel at kickoff). Ask each for at most 3 candidates.
4. Keep at most **5 candidates per run** across all scouts, best first. Drop duplicates of open or closed `scout` issues.
5. File each one as a GitHub issue labelled `scout`, using the report format below.
6. Judge them on paper (below), then label and close as the verdict says.
7. In the run summary, list what was filed, approved and rejected, with links.

## Checklist for every candidate

Hard rules (fail one and the candidate is dropped):

- **Licence** allows use in a paid product: MIT, BSD, Apache-2.0, ISC, MPL-2.0 or similar. GPL, AGPL, "non-commercial" (CC-BY-NC and the like) and no licence at all fail. A model's licence is the model card's, not the code's.
- **Free:** no paid API, key or hosted service needed to use it.
- **Runs on the owner's machine** (above): macOS arm64, and for models at most about 8B parameters at 4 bits with no CUDA-only code.
- **Safe to run:** a pinned release exists. For models, weights in `safetensors` or GGUF (owner decision oct.30.2026; neither holds executable code, while pickle `.bin`, `.pt` and `.pkl` stay banned) and no `trust_remote_code`. A GGUF model runs only on a current `llama.cpp`, Ollama or `llama-cpp-python` (0.2.72 or later), because GGUF metadata carries a chat template that older runtimes rendered unsafely (CVE-2024-34359).

Recorded facts (cite a URL for each, or write "unknown"). For Python packages, read versions, `requires_python`, wheel tags and `requires_dist` from the PyPI JSON (`https://pypi.org/pypi/<name>/json`), not from third-party listings:

- **Upkeep:** date of the last release and the last commit, open issues, and roughly how many maintainers.
- **Size:** install size, or model parameters with the memory it needs at the precision we'd use, and whether a Metal or MLX build exists.
- **What it replaces:** the Warren file, step or milestone it would replace or speed up, and what we do today.
- **Weight:** the number of hard dependencies, and any exact pin on a package Warren already uses or will choose (a provider SDK, numpy, pandas). Heavy or pinning candidates rarely pass review.
- **Fit:** any conflict with a standing rule (point-in-time, no LLM numbers, sources behind adapters, everything in this repo).

Prefer candidates that fill a gap Warren has not built yet (an upcoming milestone, a gap the docs record) over ones that replace working, tested code: replacing code that works risks the reproduce-to-the-cent invariant for little gain (lesson from the kickoff run, issues #55 to #58). A candidate that depends on an open decision (for example a local model under Decision 1) is filed only as an input to that decision.

## Report format (the issue body)

- Title: `Scout: <name> for <what it would do>`.
- Body: one paragraph on what it is; the checklist as a list with the URLs; which lane and milestone it serves; the scout's honest downside. End with the Claude Code footer.

## Judging on paper (the evaluation team)

The owner chose paper review, with no hands-on trial (oct.30.2026). For each filed candidate, run the `analyst` and the `gatekeeper` with only the issue body and the repo docs.

- **Analyst:** is this how a practitioner would solve that part, and would it break on real Phase 1 companies?
- **Gatekeeper:** do the hard rules really pass (re-check the licence and the pinned release from the URLs), does it fit the standing rules and the guardrails of Decision 11, and is the gain worth a new dependency? Ends with **GO** or **NO-GO**.

Then:

- **GO** from both: add the label `backlog`, keep `scout`, and comment with the verdicts. An Elephant takes it from there through the normal loop, where its design review decides how to use it.
- **NO-GO** from either: comment with the reason and close the issue as "not planned".
- Disagreement: treat it as NO-GO and record both views in the comment.

## Escalate to the owner only for

- Anything that costs money (a paid tier, a hosted model, a GPU).
- Forking a project into a new repository (everything stays in `warren` by default; vendoring a small file with its licence is normal backlog work).
- A candidate that would change an Accepted decision, for example replacing a data source in Decision 8 or the LLM rules in Decision 9.

## Never

- Install, clone, fork or run a candidate during a scout run.
- File more than 5 issues in one run, or refile a rejected candidate unless it has a new release that fixes the reason for the rejection.
- Post, comment or file issues anywhere outside `sonderbot-ar/warren`. Reading other repos and model pages is the job; writing to them is not.
