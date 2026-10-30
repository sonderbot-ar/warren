---
name: "warren-desk-report"
description: "Write the owner's desk entry and one-page lesson after a Warren version merges, or the weekly Warren digest."
---

# Warren desk report

The owner, Andrew, reads reports, not code, often on his phone. Warren is also how he learns finance and AI building. Write like a smart friend explaining it over a beer, not like an analyst writing a memo.

## Voice (applies to everything below)

- Lay words, short sentences. If a sentence needs a second read, rewrite it.
- No file names, function names, test names or table names in the body. Links and counts go in the one-line footer.
- A finance term is fine if you explain it in the same sentence in under ten words ("the median, the middle result").
- At most three numbers in a section, rounded, each with what it means ("5.6% typical revenue miss").
- Say bad news straight. "It's a coin flip case by case" beats "performance is mixed".
- Casual language and the odd swear word are fine when they make a point land. Never at a person, and never more than once or twice per entry.
- One analogy per lesson, from everyday life.
- No em-dashes, no arrow chains.

## Desk entry (one per merged version)

Add it to the top of the desk page (link in `docs/versions.md`). Shape:

1. **Headline:** what's different, in plain words, as a sentence. "Warren can finally grade its own homework", not "Evaluation harness v1".
2. **One-liner:** what Warren can do now that it couldn't before. Two sentences max.
3. **Did it get better?** From M3 on, lead with the forecast error against the previous version and against the lazy rival (copy last year). Up to three number tiles, then two or three sentences on what they mean, including the worst miss.
4. **What's new:** up to three bullets, each under 20 words, each saying why it matters.
5. **What the reviewers caught:** the one thing worth knowing, plus "smaller stuff is parked as to-dos". Skip the issue numbers.
6. **Your move:** decisions waiting, or skip the section when there are none (the top strip already says so).
7. **Lesson** (collapsed under the entry).
8. **Footer line:** milestone, PR links, test count, reproduce check.

Never invent a number. Quote it from a test run, a command's output, a stored run or a batch report. Take every fact from the PR, the commits and the review. A lighter model is fine for the writing.

## Lesson (one per version)

Under 250 words. One big idea, one everyday analogy, then the two or three tricks in the code that make the idea work, in plain words. End with where else this is useful, and its main limit, in one line each.

## Weekly digest

Under 100 words, three short parts:

- **Shipped:** one line per version, with a link to its desk entry. "Nothing shipped" is fine; then say why.
- **Next:** what the team is working on now.
- **Need from you:** decisions waiting and anything that blocked work (usage limits, a failing check), or "nothing".
