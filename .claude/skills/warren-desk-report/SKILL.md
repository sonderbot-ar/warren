---
name: "warren-desk-report"
description: "Write the owner's desk entry and one-page lesson after a Warren version merges, or the weekly Warren digest."
---

# Warren desk report

The owner, Andrew, reads reports, not code. Warren is also how he learns finance and AI building. Write in plain language with short sentences and no jargon left unexplained. Avoid em-dashes and arrow chains.

## Desk entry (one per merged version)

Add it to the top of the desk page. Find the page's link in `docs/versions.md` or in the project thread. Use this shape:

1. **Header:** version (from `docs/versions.md`), date, milestone or backlog item, PR links.
2. **In one line:** what Warren can do now that the previous version couldn't.
3. **What changed, and why it's better:** 2 to 5 items. Each is one sentence on the change and one on why it beats the previous version.
4. **Evidence:** test count before and after; whether the reproduce-to-the-cent check holds; from M3 on, forecast error against the baseline, and lead with that number. Never invent a number. Quote it from a test run, a command's output or a stored run.
5. **Open arguments:** one line per disagreement from the review that's still open.
6. **Waiting on you:** decisions from the trigger list, or "nothing".
7. **Lesson:** a link to it.

Use a lighter model for the writing. Take every fact from the PR, the commits and the review comments.

## Lesson (one page per version)

Treat the version as one class. Show the concepts as they actually work together in the code, not one at a time. Cover:

- the decisions taken and why
- new tools or libraries and why they were chosen
- what each new script or module does, in a sentence each
- for each concept: why it does or doesn't suit Warren, which kinds of projects benefit from it and which don't, and its limits

One page at most. Offer a deeper lesson only if the owner asks.

## Weekly digest

Cover the versions shipped this week, with one line each and a link to the desk entry. Add what's next, any decisions waiting on the owner, and anything that blocked work, such as usage limits, a failing check or an open question. Keep it under 150 words.