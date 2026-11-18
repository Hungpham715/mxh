# Dataset quality audit (generated)

- Created: 2026-11-18T07:33:39.548967+00:00
- Graph source: local_snapshot (offline/data/processed + derived), NOT live Aura
- Snapshot manifest sha256: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`
- Candidates: 10619 (duplicates removed: 388)
- Silver validated (independent raw-table oracle agreed): 10619
- Rejected: 0 — reasons {}
- Human/independent gold: **0** (no reviewer in this run; G6 cannot PASS on silver alone)
- Leakage check: **PASS** {'anchor_entities_in_multiple_splits': 0, 'questions_in_multiple_splits': 0, 'verdict': 'PASS'}

## Per intent

| intent | silver | train | val | test |
|---|---|---|---|---|
| author_affiliations | 1283 | 920 | 185 | 178 |
| author_papers | 2124 | 1487 | 322 | 315 |
| author_path | 285 | 258 | 15 | 12 |
| coauthor_affiliations | 1270 | 913 | 182 | 175 |
| coauthors | 1289 | 905 | 197 | 187 |
| network_top | 3 | 2 | 0 | 1 |
| org_collaborations | 531 | 373 | 85 | 73 |
| paper_authors | 1216 | 877 | 176 | 163 |
| paper_citations | 42 | 34 | 4 | 4 |
| paper_venue | 1228 | 885 | 179 | 164 |
| shared_papers | 1300 | 1195 | 46 | 59 |
| topic_papers | 30 | 25 | 0 | 5 |
| unknown | 18 | 13 | 1 | 4 |

## Per expected status

- ambiguous: 1005
- answered: 9024
- clarify: 6
- not_found: 463
- out_of_scope: 18
- partial: 103

## Random sample (10 silver cases, seed-fixed)

- `L-2312fbd121d37df2` [train/answered] Cyril Leung có những bài báo nào năm 2023? → 1 result(s)
- `L-60c2a6ebf6f3e06d` [test/answered] Who are the co-authors of Lukas Wolf? → 6 result(s)
- `L-0fa159a640dd775e` [train/answered] Suzan Verberne và Yumeng Wang có bài báo chung nào? → 1 result(s)
- `L-2b6ecf63bb4bc4c3` [val/answered] Liệt kê các bài báo của tác giả Alex Wilf. → 1 result(s)
- `L-c558bc998f02659a` [train/answered] Liệt kê các bài báo của tác giả Greg Durrett. → 2 result(s)
- `L-e35287db88d3bf20` [test/answered] In which venue did “Multimodal Neural Machine Translation: A Survey of the State of the Art” appear? → 1 result(s)
- `L-0029c1e8f4f1498e` [train/answered] Bhavya Kailkhura đã viết chung với những ai? → 7 result(s)
- `L-677d13edcb1a4672` [test/answered] Xiaotong Li và Zeyuan Wang có bài báo chung nào? → 1 result(s)
- `L-90f5c1c05f00915b` [val/answered] In which venue did “is gpt powerful enough to analyze the emotions of memes?” appear? → 1 result(s)
- `L-146c4bc3ca5f0715` [train/answered] Liệt kê các bài báo của tác giả Junwon Sung. → 1 result(s)
