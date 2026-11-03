# Sources

| Source | Endpoint | Used for | Notes |
|---|---|---|---|
| ACL Anthology | `https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml/<collection>.xml` | ACL id, title, abstract, ordered authors, printed affiliation, DOI | official XML data; accessed 2026-11-03 |
| arXiv | `https://export.arxiv.org/api/query` (Atom) | arXiv id, title, abstract, authors, primary category | 3.5 s between calls, User-Agent with contact, cache |
| OpenAlex | `https://api.openalex.org/works/doi:<DOI>` | W/A/I ids, per-work authorships + institutions, referenced_works | exact DOI lookups only; arXiv uses 10.48550/arxiv.<id>; key optional |

Selection (`configs/scope.yaml`, fixed before looking at graph metrics): 140 papers per main volume
(2023–2025 ACL long, EMNLP main) by systematic sampling over ascending paper id; Findings fallback not needed.
arXiv: per month 7 earliest-submitted papers with primary category cs.CL (252 total).

Coverage (real run): 1,092 records, 1,090 matched in OpenAlex, 1 arXiv preprint merged into its ACL version,
334 works with references (26 in-corpus citations), 0 missing abstracts.

Wikipedia is not a primary source: it has no per-paper author lists, per-authorship affiliations or citations,
and covers only a small fraction of NLP researchers.

Known source issues: OpenAlex sometimes attaches institutions that the author did not print on the paper, and in
23 works it copies paper-level affiliations onto every author. Mitigation in `normalize.py` (see evaluation/fix_log.json).
