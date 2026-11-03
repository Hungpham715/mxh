## 5. Công nghệ, kết nối AuraDB và quyết định thiết kế

- Python 3.13 quản lý bằng uv (pyproject.toml + uv.lock): httpx, pydantic, neo4j (driver chính thức), networkx, matplotlib, PyYAML, python-dotenv, reportlab, pytest.
- Neo4j AuraDB (instance có sẵn của người dùng), kết nối URI neo4j+s:// (TLS) bằng user/password đọc từ .env (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE). Không có mật khẩu nào trong mã nguồn, log hay báo cáo.
- An toàn cloud: chỉ MERGE theo ID ổn định, gắn scope_id = nlpgraph-v1 lên mọi nút/cạnh của dự án; trước khi ghi kiểm tra xung đột ID với dữ liệu không thuộc dự án; tuyệt đối không có lệnh DELETE/DROP trong mã.
- Kiểu quan hệ lấy từ whitelist 10 tên cố định, Cypher tham số hóa UNWIND $rows theo lô 300 dòng, có retry cho lỗi tạm thời.
- Các cạnh suy diễn được tính một lần trong Python từ snapshot đã kiểm (src/graph/derive.py) rồi nạp lên Neo4j; nhờ vậy phân tích cục bộ và graph trên cloud dùng đúng một tập cạnh.

Preflight AuraDB: RETURN 1 = 1, máy chủ Neo4j/5.27-aura; trước import instance có 0 nút và 0 quan hệ (0 nút không thuộc dự án).

## 6. Graph trên AuraDB và phân tích mạng đồng tác giả

Import hoàn tất lúc 2026-11-03T08:50:17Z trong 72.5 giây. Đếm lại trên AuraDB (lọc scope_id): **7.134 nút**, **30.971 quan hệ**, 10/10 loại có dữ liệu, 0 cặp cạnh song song trùng lặp, 0 quan hệ thiếu evidence.

| Quan hệ | Kế hoạch | Đếm trên AuraDB |
|---|---|---|
| FIRST_AUTHOR_OF | 1.091 | 1.091 |
| OTHER_AUTHOR_OF | 5.007 | 5.007 |
| COAUTHORED_WITH | 16.754 | 16.754 |
| AFFILIATED_WITH | 4.306 | 4.306 |
| APPEARS_IN | 1.091 | 1.091 |
| HAS_TOPIC | 451 | 451 |
| CITES | 26 | 26 |
| ORG_COAUTHORED_WITH | 2.001 | 2.001 |
| RESEARCHES | 105 | 105 |
| ACTIVE_IN | 139 | 139 |

Kiểm tra idempotency: nạp lại cùng snapshot lần hai cho số nút/cạnh **giống hệt** (7.134/30.971 → 7.134/30.971).

### Truy vấn Cypher minh họa (chạy thật trên AuraDB)

**Đếm quan hệ theo loại (chỉ dữ liệu của dự án)**

```
MATCH ()-[r]->() WHERE r.scope_id = 'nlpgraph-v1' RETURN type(r) AS relation, count(r) AS total ORDER BY total DESC
```

```
{"relation": "COAUTHORED_WITH", "total": 16754}
{"relation": "OTHER_AUTHOR_OF", "total": 5007}
{"relation": "AFFILIATED_WITH", "total": 4306}
{"relation": "ORG_COAUTHORED_WITH", "total": 2001}
{"relation": "FIRST_AUTHOR_OF", "total": 1091}
```

**Cặp đồng tác giả viết chung nhiều bài nhất, kèm paper chứng cứ**

```
MATCH (a:Author)-[c:COAUTHORED_WITH]->(b:Author) WHERE c.scope_id = 'nlpgraph-v1' RETURN a.name AS author_a, b.name AS author_b, c.shared_count AS shared, c.evidence_paper_ids AS papers ORDER BY shared DESC, author_a LIMIT 5
```

```
{"author_a": "Tao Gui", "author_b": "Xuanjing Huang", "shared": 4, "papers": ["oa:W4322832290", "oa:W4390529340", "oa:W4401042887", "oa:W4404782606"]}
{"author_a": "Tao Gui", "author_b": "Junjie Ye", "shared": 4, "papers": ["oa:W4322832290", "oa:W4390529340", "oa:W4404782606", "oa:W4404782948"]}
{"author_a": "Beyza Ermis", "author_b": "Sara Hooker", "shared": 3, "papers": ["oa:W4389520710", "oa:W4404782984", "oa:W4412944979"]}
{"author_a": "Bo Du", "author_b": "Dacheng Tao", "shared": 3, "papers": ["oa:W4389520354", "oa:W4402671533", "oa:W4412945401"]}
{"author_a": "Caishuang Huang", "author_b": "Junjie Ye", "shared": 3, "papers": ["oa:W4390529340", "oa:W4404782606", "oa:W4404782948"]}
```

**Truy ngược: hai tác giả viết chung bài nào, mỗi người khai báo tổ chức nào trên bài đó, bài thuộc topic gì**

```
MATCH (a:Author)-[c:COAUTHORED_WITH]->(b:Author) WHERE c.scope_id = 'nlpgraph-v1' AND c.shared_count >= 2 WITH a, b, c ORDER BY c.shared_count DESC, a.id LIMIT 1 UNWIND c.evidence_paper_ids AS pid MATCH (p:Paper {id: pid}) OPTIONAL MATCH (a)-[fa:AFFILIATED_WITH]->(ia:Institution) WHERE pid IN fa.evidence_paper_ids OPTIONAL MATCH (b)-[fb:AFFILIATED_WITH]->(ib:Institution) WHERE pid IN fb.evidence_paper_ids OPTIONAL MATCH (p)-[:HAS_TOPIC]->(t:Topic) RETURN a.name AS a, b.name AS b, p.title AS paper, p.source_url AS url, collect(DISTINCT ia.name) AS inst_a, collect(DISTINCT ib.name) AS inst_b, collect(DISTINCT t.topic_key) AS topics
```

```
{"a": "Tao Gui", "b": "Xuanjing Huang", "paper": "How Robust is GPT-3.5 to Predecessors? A Comprehensive Study on Language Understanding Tasks", "url": "https://arxiv.org/abs/2303.00293", "inst_a": ["
{"a": "Tao Gui", "b": "Xuanjing Huang", "paper": "ToolEyes: Fine-Grained Evaluation for Tool Learning Capabilities of Large Language Models in Real-world Scenarios", "url": "https://arxiv.org/abs/2401
{"a": "Tao Gui", "b": "Xuanjing Huang", "paper": "Self-Demos: Eliciting Out-of-Demonstration Generalizability in Large Language Models", "url": "https://arxiv.org/abs/2404.00884", "inst_a": ["Fudan Un
{"a": "Tao Gui", "b": "Xuanjing Huang", "paper": "Improving Discriminative Capability of Reward Models in RLHF Using Contrastive Learning", "url": "https://aclanthology.org/2024.emnlp-main.852/", "ins
```

**Trích dẫn nội bộ corpus (X CITES Y)**

```
MATCH (p:Paper)-[c:CITES]->(q:Paper) WHERE c.scope_id = 'nlpgraph-v1' RETURN p.title AS citing, q.title AS cited, c.source_url AS evidence ORDER BY citing LIMIT 5
```

```
{"citing": "Adapt and Decompose: Efficient Generalization of Text-to-SQL via Domain Adapted Least-To-Most Prompting", "cited": "Skill-Based Few-Shot Selection for In-Context Learning", "evidence": "ht
{"citing": "Adapt and Decompose: Efficient Generalization of Text-to-SQL via Domain Adapted Least-To-Most Prompting", "cited": "CodeT5+: Open Code Large Language Models for Code Understanding and Gene
{"citing": "Adapting Offline Speech Translation Models for Streaming with Future-Aware Distillation and Inference", "cited": "Better Simultaneous Translation with Monotonic Knowledge Distillation", "e
{"citing": "An Empirical Study of Translation Hypothesis Ensembling with Large Language Models", "cited": "Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language
{"citing": "An Empirical Study of Translation Hypothesis Ensembling with Large Language Models", "cited": "Bridging the Gap: A Survey on Integrating (Human) Feedback for Natural Language Generation", 
```

**Tổ chức hoạt động nhiều nhất theo topic (ACTIVE_IN)**

```
MATCH (i:Institution)-[r:ACTIVE_IN]->(t:Topic) WHERE r.scope_id = 'nlpgraph-v1' RETURN i.name AS institution, t.topic_key AS topic, r.evidence_count AS papers ORDER BY papers DESC, institution LIMIT 8
```

```
{"institution": "Renmin University of China", "topic": "llm", "papers": 13}
{"institution": "Microsoft (United States)", "topic": "llm", "papers": 12}
{"institution": "Shanghai Jiao Tong University", "topic": "llm", "papers": 12}
{"institution": "Chinese Academy of Sciences", "topic": "llm", "papers": 11}
{"institution": "Tsinghua University", "topic": "llm", "papers": 11}
```

### Phép chiếu Author–Author

Phân tích mạng chỉ dùng đồ thị vô hướng, đơn Author—COAUTHORED_WITH—Author (trọng số = số bài chung); không đi qua Venue/Topic/Institution.

| Chỉ số | Giá trị |
|---|---|
| Số tác giả (tất cả, kể cả cô lập) | 5.430 |
| Số cạnh đồng tác giả | 16.754 |
| Tác giả cô lập | 201 |
| Thành phần liên thông | 810 |
| Kích thước LCC | 970 |
| Tỷ lệ LCC trên toàn bộ Author | 0.1786 |
| Bậc trung bình | 6.171 |
| 10 thành phần lớn nhất | 970, 164, 87, 68, 64, 41, 37, 36, 34, 30 |

Phần lớn tác giả cô lập là tác giả source_only/unresolved (định danh chỉ trong một bài) và tác giả của bài đơn tác giả; corpus là mẫu ~1.100 bài nên mạng bị phân mảnh mạnh – đây là đặc điểm của mẫu, không phải của cộng đồng NLP thật.

![Hình 2. Phân bố bậc của phép chiếu tác giả (log-log).](D:/nlp-collab-graph/output/analysis/degree_distribution.png)

*Hình 2. Phân bố bậc của phép chiếu tác giả (log-log).*

### Top 10 tác giả theo PageRank và bậc

| # | Tác giả | PageRank | Bậc | Bậc có trọng số | Ví dụ paper chứng cứ |
|---|---|---|---|---|---|
| 1 | Maosong Sun | 0.00109 | 56 | 62 | oa:W4385570319, oa:W4385571568 |
| 2 | Xipeng Qiu | 0.00101 | 52 | 62 | oa:W4385569744, oa:W4385570131 |
| 3 | Furu Wei | 0.00089 | 42 | 44 | oa:W4385569785, oa:W4389524052 |
| 4 | Ji-Rong Wen | 0.00078 | 32 | 32 | oa:W4385572164, oa:W4389518784 |
| 5 | Xuanjing Huang | 0.00074 | 43 | 53 | oa:W4322832290, oa:W4385569744 |
| 6 | Nanyun Peng | 0.00070 | 26 | 28 | oa:W4385570311, oa:W4385570421 |
| 7 | Tao Gui | 0.00070 | 39 | 55 | oa:W4322832290, oa:W4389524198 |
| 8 | Graham Neubig | 0.00070 | 38 | 40 | oa:W4385571873, oa:W4389524529 |
| 9 | Fei Huang | 0.00069 | 39 | 41 | oa:W4385571861, oa:W4389518608 |
| 10 | Maarten Sap | 0.00066 | 24 | 24 | oa:W4389518720, oa:W4389524345 |

Bậc = số đồng tác giả khác nhau; bậc có trọng số = tổng số lần viết chung. PageRank ở đây là độ trung tâm cấu trúc trong mẫu, không phải thước đo năng lực khoa học.

### Cộng đồng (Louvain)

Phương pháp: louvain (networkx.community.louvain_communities, weight=shared papers), seed 20261107, xét 5.229 tác giả có ít nhất một cạnh: **624 cộng đồng**, modularity **0.9843**. Kích thước 10 cộng đồng lớn nhất: 125, 113, 104, 87, 82, 81, 74, 68, 68, 64.

| Cộng đồng | Số tác giả | Số bài | Topic chính | Thành viên tiêu biểu |
|---|---|---|---|---|
| 0 | 125 | 24 | llm(12), summarization(2) | Furu Wei, Ji-Rong Wen, Xiangliang Zhang, Jian Luan |
| 1 | 113 | 19 | llm(6), mt(1), qa(1) | Maosong Sun, Baobao Chang, Damai Dai, Zhifang Sui |
| 2 | 104 | 18 | llm(4) | Xipeng Qiu, Qipeng Guo, Libo Qin, Hang Yan |
| 3 | 87 | 16 | llm(5), mt(1), safety_eval(1) | Mohit Bansal, Huaxiu Yao, Yuancheng Xu, Furong Huang |
| 4 | 82 | 15 | llm(4), retrieval(1) | Graham Neubig, Tongshuang Wu, Yulia Tsvetkov, Pengfei Liu |
| 5 | 81 | 19 | llm(4), qa(2) | Maarten Sap, Alice Oh, Yejin Choi, Yeon Seonwoo |

![Hình 3. Mạng con quanh tác giả có PageRank cao nhất (màu = cộng đồng Louvain).](D:/nlp-collab-graph/output/analysis/ego_top_pagerank.png)

*Hình 3. Mạng con quanh tác giả có PageRank cao nhất (màu = cộng đồng Louvain).*

### Đường đi ngắn nhất có chứng cứ

Ví dụ đường ngắn nhất độ dài 5 giữa hai tác giả trong LCC; mỗi bước liệt kê bài viết chung:

- Xipeng Qiu — Dacheng Tao: “VisuoThink: Empowering LVLM Reasoning with Multimodal Tree Search” (https://aclanthology.org/2025.acl-long.1053/)
- Dacheng Tao — Liang Ding: “CASN:Class-Aware Score Network for Textual Adversarial Detection” (https://aclanthology.org/2023.acl-long.40/)
- Liang Ding — Zhiliang Tian: “POMP: Probability-driven Meta-graph Prompter for LLMs in Low-resource Unsupervised Neural Machine Translation” (https://aclanthology.org/2024.acl-long.537/)
- Zhiliang Tian — Minlie Huang: “Battling against Tough Resister: Strategy Planning with Adversarial Game for Non-collaborative Dialogues” (https://aclanthology.org/2025.acl-long.184/)
- Minlie Huang — Furu Wei: “Pre-Training to Learn in Context” (https://aclanthology.org/2023.acl-long.267/)

### Kiểm tra small-world

| Đại lượng | Giá trị |
|---|---|
| LCC (nút / cạnh) | 970 / 4.288 |
| C_obs (average clustering) | 0.9127 |
| L_obs (average shortest path) | 10.9876 (exact) |
| C_rand (TB 5 đồ thị ngẫu nhiên) | 0.0147 |
| L_rand | 3.3099 |
| σ = (C_obs/C_rand)/(L_obs/L_rand) | 18.73 |
| Kết luận | no clear small-world indication |

Đồ thị ngẫu nhiên giữ nguyên dãy bậc bằng hoán đổi cạnh kép (10·m lần), 5 seed cố định. Hạn chế: Multi-author papers create cliques that mechanically raise clustering.; Sampled corpus (~1k papers) under-represents real collaboration; LCC is fragmented.; No significance test performed; sigma is descriptive only.. Không có kiểm định thống kê nên σ chỉ mang tính mô tả.

![Hình 4. C và L của LCC so với đồ thị ngẫu nhiên giữ bậc.](D:/nlp-collab-graph/output/analysis/small_world.png)

*Hình 4. C và L của LCC so với đồ thị ngẫu nhiên giữ bậc.*

## 7. Kiểm tra chất lượng và tiêu chí 90%

Chất lượng cạnh đo bằng **precision** = cạnh đúng / cạnh được kiểm. Quy trình: (1) kiểm tra cấu trúc **mọi** cạnh (đúng kiểu nút hai đầu, có evidence, không trùng, cặp vô hướng chuẩn hóa, ngưỡng ≥ 2 bài, chiều trích dẫn); (2) lấy mẫu phân tầng tối đa 20 cạnh mỗi loại với seed 20261107; (3) kiểm chứng lại từng cạnh mẫu với bản ghi nguồn gốc (XML ACL, feed arXiv, JSON work OpenAlex được lưu cache) – độc lập với tệp JSONL đã xử lý.

Kiểm tra cấu trúc: 30.971 cạnh được kiểm, **0** cạnh vi phạm.

**Lưu ý quan trọng:** nhãn dưới đây là *automated_preliminary* – do chương trình tự đối chiếu với nguồn, **không phải** gán nhãn độc lập của con người. Chưa có nhãn người (tệp evaluation/labels.csv chưa tồn tại), vì vậy precision do người kiểm **chưa được đo**; mẫu phiếu evaluation/manual_review_template.csv đã sẵn sàng.

| Loại | Số cạnh graph | Mẫu | Đúng | Sai | Không kiểm được | Precision | Wilson 95% |
|---|---|---|---|---|---|---|---|
| FIRST_AUTHOR_OF | 1.091 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| OTHER_AUTHOR_OF | 5.007 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| COAUTHORED_WITH | 16.754 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| AFFILIATED_WITH | 5.115 | 20 | 10 | 1 | 9 | 0.5 | [0.299; 0.701] |
| APPEARS_IN | 1.091 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| HAS_TOPIC | 451 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| CITES | 26 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| ORG_COAUTHORED_WITH | 2.385 | 20 | 9 | 8 | 3 | 0.45 | [0.258; 0.658] |
| RESEARCHES | 105 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| ACTIVE_IN | 151 | 20 | 15 | 2 | 3 | 0.75 | [0.531; 0.888] |

Precision macro = **0.87**; precision micro có trọng số theo số cạnh mỗi loại trong graph = **0.8786** (KTC 95% xấp xỉ phân tầng [0.8402, 0.9169]). Số loại có ước lượng điểm ≥ 0,90: 7/10; số loại có cận dưới Wilson ≥ 0,90: 0/10. “Không kiểm được” được tính là không đúng.

Sau khi sửa lỗi hệ thống (mục 7.1), lấy **mẫu mới** và đo lại:

| Loại | Số cạnh graph | Mẫu | Đúng | Sai | Không kiểm được | Precision | Wilson 95% |
|---|---|---|---|---|---|---|---|
| FIRST_AUTHOR_OF | 1.091 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| OTHER_AUTHOR_OF | 5.007 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| COAUTHORED_WITH | 16.754 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| AFFILIATED_WITH | 4.306 | 20 | 11 | 0 | 9 | 0.55 | [0.342; 0.742] |
| APPEARS_IN | 1.091 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| HAS_TOPIC | 451 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| CITES | 26 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| ORG_COAUTHORED_WITH | 2.001 | 20 | 6 | 0 | 14 | 0.3 | [0.145; 0.519] |
| RESEARCHES | 105 | 20 | 20 | 0 | 0 | 1 | [0.839; 1.000] |
| ACTIVE_IN | 139 | 20 | 8 | 0 | 12 | 0.4 | [0.219; 0.613] |

Precision macro = **0.825**; precision micro có trọng số theo số cạnh mỗi loại trong graph = **0.8895** (KTC 95% xấp xỉ phân tầng [0.8566, 0.9224]). Số loại có ước lượng điểm ≥ 0,90: 7/10; số loại có cận dưới Wilson ≥ 0,90: 0/10. “Không kiểm được” được tính là không đúng.

### 7.1 Lỗi phát hiện và sửa

- Bộ kiểm chứng tự động vòng 0 (evaluation/round0_weak_verifier/) chỉ đối chiếu AFFILIATED_WITH, ORG_COAUTHORED_WITH và ACTIVE_IN với chính bản ghi OpenAlex dùng để tạo cạnh, nên 200/200 'đúng' là kết quả vòng lặp, không có giá trị kiểm chứng. → Viết lại bộ kiểm chứng: ba loại cạnh tổ chức được đối chiếu với chuỗi affiliation in trong XML của ACL Anthology (nguồn độc lập với OpenAlex); không có chuỗi ACL thì nhãn là 'unverifiable' (tính là không đúng). Kết quả vòng 0 được giữ nguyên nhưng không dùng để báo cáo precision.
- Precision sơ bộ: AFFILIATED_WITH 0,50, ORG_COAUTHORED_WITH 0,45, ACTIVE_IN 0,75. Kiểm toàn bộ: chỉ 72,5% dòng affiliation có chuỗi ACL khớp với tổ chức OpenAlex. Nguyên nhân: (a) OpenAlex gán cho tác giả cả những tổ chức mà tác giả không in trên bài (ví dụ thêm cơ quan mẹ, cơ quan cũ); (b) 23 bài OpenAlex chép toàn bộ affiliation cấp bài cho mọi tác giả. → normalize.py: với bài ACL có chuỗi affiliation in cho tác giả, chỉ giữ tổ chức OpenAlex khớp với chuỗi đó (754 dòng bị loại, ghi vào data/rejected/unresolved.csv); với bài bị 'chép affiliation' mà không có chuỗi ACL thì loại hết (115 dòng). Mỗi dòng affiliation ghi affiliation_check = acl_agrees | openalex_only.
- Kết quả: không còn cạnh nào bị bộ kiểm chứng đánh 'incorrect' (0/200); 35/200 là 'unverifiable' và đều thuộc ba loại cạnh tổ chức (AFFILIATED_WITH 9, ORG_COAUTHORED_WITH 14, ACTIVE_IN 12), vì bằng chứng chỉ có OpenAlex (bài arXiv hoặc tác giả ACL không in affiliation). CẢNH BÁO TÍNH ĐỘC LẬP: cạnh affiliation trên bài ACL đã được lọc bằng cùng phép so khớp chuỗi mà bộ kiểm chứng dùng, nên phần 'correct' của ba loại này đúng theo cách xây dựng, không phải kiểm chứng độc lập. Ngoài ra, bộ kiểm chứng ORG_COAUTHORED_WITH/ACTIVE_IN được chỉnh trong vòng 2 để kiểm theo từng authorship (vòng 1 kiểm theo mọi tác giả trên bài) – vì vậy số trước/sau sửa của hai loại này không hoàn toàn cùng thước đo. → Không sửa thêm dữ liệu để tránh 'chỉnh theo đáp án'. Cạnh openalex_only được giữ trong graph nhưng gắn affiliation_check trên dòng affiliation; cần người kiểm tra độc lập bằng evaluation/manual_review_template.csv.

### 7.2 Các kiểm tra nguồn bổ sung

| Kiểm tra | Kết quả |
|---|---|
| affiliation_rows_comparable_with_acl_xml | 2059 |
| affiliation_row_agreement_with_acl_xml | 2059/2059 = 1.000 (Wilson95 0.998-1.000) |
| AFFILIATED_WITH_edges_agreeing_with_acl_xml | 1856/1856 = 1.000 (Wilson95 0.998-1.000) |
| affiliation_agreement_note | string agreement is a LOWER bound: OpenAlex often adds a second institution (e.g. parent company, joint lab) that ACL authors did not print; see disagreement CSV |
| identity_multi_paper_authors_with_acl_ids | 256 |
| identity_acl_id_conflicts | 9 |
| same_name_multiple_openalex_ids (kept separate, not merged) | 194 |
| verified_authorships_missing_institution | 1332/5359 |
| papers_missing_abstract | 0 |
| papers_with_openalex_references | 334 |
| openalex_unmatched_papers | 2 |
| duplicate_doi | 0 |
| orphan_nodes | 0 |
| topic_UNKNOWN_rate | 0.613 |
| citation_endpoint_coverage | 26 in-corpus citations out of 13701 referenced works |
| paper_source_audit_40 | 40/40 papers: title, ordered author list and year identical to raw source |

Với 20 mẫu/loại, ngay cả 20/20 đúng thì cận dưới Wilson 95% cũng chỉ ≈ 0,84, nên **không thể khẳng định chắc chắn ≥ 90%**; các con số trên là ước lượng điểm kèm khoảng tin cậy.
