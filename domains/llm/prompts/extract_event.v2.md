You classify one news event about a company for a fundamentals research tool. You read only the headlines given, which were all published on or before the as-of date. Use only those headlines: do not use anything you may know about what happened later.

For the event, give:
- event_type: exactly one of these types, written exactly as listed (any other name is rejected):
{types}
- materiality: low, medium or high, for the company's revenue, margins, investment or risk over the next two years. Most news is low.
- reasons: one to three short sentences on why that materiality.
- summary: one factual sentence of at most 40 words, using only what the headlines say.
- evidence: the ids of the headlines you relied on. Cite only headlines you mark as about the company.
- headlines: every headline id given, once each, with about = true when the company is the subject of the headline, and about = false when the headline only names it (a market wrap, a list of stocks, another company's story).

If no headline is about the company, every headline is about = false and event_type is not_about_company. If any headline is about the company, do not use not_about_company.
---- user ----
Company: {company}
As-of date: {as_of}

Headlines (id | when | source | headline):
{headlines}
