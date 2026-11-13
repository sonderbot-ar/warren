# Concept map versions

Each `<sha256>.csv` here is a byte-for-byte copy of a `concept_map.csv` that runs may have been made with, named by its SHA-256 (backlog #357). A stored run is rebuilt through the copy whose name is its `runs.concept_map_sha256`. Never edit or delete a copy: add a new one, and a line below, in the same commit as the map edit. `tests/fundamentals/test_concepts.py` fails until today's map has its copy. After a map edit, re-ingest every company (`python -m domains.fundamentals ingest --all`) before making new runs, so no run carries the new fingerprint without the new tags' facts.

| Fingerprint | From | What changed and why |
|---|---|---|
| `2a263604a945` | oct.26.2026 (`1e81c37`) | Securities and fallback items, the optional gate. The map every run up to v0.9.64 was made with. |
