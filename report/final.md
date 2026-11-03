# Mạng lưới các tác giả và tổ chức nghiên cứu về Xử lý ngôn ngữ tự nhiên (NLP) quốc tế

**Báo cáo kỹ thuật** – dự án đồ thị tri thức đồng tác giả, tổ chức, chủ đề và trích dẫn xây dựng từ ACL Anthology, arXiv cs.CL và OpenAlex, lưu trữ trên Neo4j AuraDB. Tất cả số liệu trong báo cáo được sinh tự động từ các tệp đầu ra thật của pipeline (manifest tạo lúc 2026-11-03T08:33:17Z, scope_id **nlpgraph-v1**). Không có số liệu nào được điền tay.

*Ghi chú về tác giả báo cáo:* mã nguồn, dữ liệu và báo cáo được thực hiện bởi một tác tử lập trình tự động theo đặc tả architecture.md và prompt.md; báo cáo không ghi tên thành viên hay tỷ lệ phân công vì không có thông tin đó được cung cấp.

## 1. Đề bài, phạm vi và tiêu chí đo được

Đề bài: “Mạng lưới các tác giả và tổ chức nghiên cứu về Xử lý ngôn ngữ tự nhiên (NLP) Quốc tế”, liên kết công bố khoa học, tác giả, tổ chức được khai báo và trích dẫn từ ACL/arXiv. Câu hỏi trung tâm mà hệ thống phải trả lời là: *hai tác giả A và B đã viết chung bài nào, khi viết bài đó mỗi người khai báo tổ chức nào, các bài ấy thuộc chủ đề gì và họ nằm trong cộng đồng nghiên cứu nào?* – và mọi câu trả lời phải truy ngược được tới paper ID và URL nguồn.

Văn bản đề gốc ghi ngưỡng “2000 nghìn nút”, cách viết này mơ hồ (2.000 hay 2.000.000). Dự án chọn mức bảo thủ **≥ 2.000 nút, ≥ 5.000 cạnh duy nhất và đủ 10 loại quan hệ có dữ liệu thật**; cách hiểu này **chưa được giảng viên xác nhận** và được nêu lại ở phần kết luận.

| Tiêu chí | Kết quả thực đo | Trạng thái |
|---|---|---|
| Corpus 1.000–1.200 paper duy nhất | 1.091 paper (ACL 840, arXiv 251) | Đạt |
| ≥ 2.000 nút | 7.134 | Đạt |
| ≥ 5.000 cạnh duy nhất | 30.971 | Đạt |
| 10/10 loại quan hệ có dữ liệu | 10/10 | Đạt |
| ≥ 1.000 Author (đo riêng) | 5.430 | Đạt |
| Graph trên Neo4j AuraDB | Có | Đạt |
| Precision cạnh ≥ 90% (mỗi type & micro) | Chưa có nhãn người; tự động sơ bộ micro 0.8786 | Xem mục 7 |

## 2. Nguồn dữ liệu học thuật và quy tắc chọn mẫu cố định

Ba nguồn chính được dùng, đúng vai trò mô tả trong kiến trúc:

- <b>ACL Anthology</b> – tệp XML chính thức trong kho acl-org/acl-anthology (data/xml/&lt;collection&gt;.xml). Cung cấp ACL ID, tiêu đề, abstract, danh sách tác giả theo thứ tự, DOI và URL. Không scrape HTML.
- <b>arXiv API</b> (export.arxiv.org/api/query) – truy vấn cat:cs.CL theo từng tháng, User-Agent có thông tin liên hệ, giãn cách 3,5 giây giữa các yêu cầu, có cache.
- <b>OpenAlex</b> – tra cứu đúng một work theo DOI (/works/doi:&lt;DOI&gt;; với arXiv dùng DOI 10.48550/arxiv.&lt;id&gt;). Lấy authorships (tác giả, author_position, institutions theo từng bài), referenced_works và abstract_inverted_index.

Ngày chốt metadata: acl-org/acl-anthology master XML, accessed 2026-11-03. Quy tắc chọn được ghi trong configs/scope.yaml **trước** khi xem bất kỳ số liệu graph nào: với mỗi volume chính (ACL long / EMNLP main các năm 2023–2025) lấy 140 bài bằng chọn hệ thống theo paper ID tăng dần (chỉ số floor(i·N/140)); Findings là phương án dự phòng nhưng không cần dùng vì mọi volume chính đều đủ số lượng. Với arXiv, mỗi tháng lấy 7 bài đầu tiên theo ngày nộp tăng dần có *primary category* là cs.CL.

| Collection | Volume | Số bài có sẵn | Đã chọn |
|---|---|---|---|
| 2023.acl | long | 911 | 140 |
| 2023.emnlp | main | 1.047 | 140 |
| 2024.acl | long | 864 | 140 |
| 2024.emnlp | main | 1.268 | 140 |
| 2025.acl | long | 1.602 | 140 |
| 2025.emnlp | main | 1.809 | 140 |

Đầu vào: 840 bản ghi ACL, 252 bản ghi arXiv; 1.090/1.092 tra cứu OpenAlex khớp DOI. Sau khử trùng còn 1.091 paper; 1 bản arXiv được xác định là cùng work OpenAlex với một bài ACL và được gộp làm alias (giữ bản hội nghị). Số paper không khớp OpenAlex: 2.

### Vì sao Wikipedia không phải nguồn chính

Wikipedia không có danh sách đồng tác giả theo từng bài, không có tổ chức khai báo theo từng công bố và không có danh sách trích dẫn theo bài; chỉ một phần nhỏ nhà nghiên cứu NLP có trang Wikipedia. Do đó các quan hệ cần chứng cứ theo bài (đồng tác giả, affiliation theo authorship, citation) phải lấy từ nguồn thư mục học (ACL Anthology, arXiv, OpenAlex). Wikipedia chỉ phù hợp để đối chiếu thủ công tên tổ chức khi nghi ngờ, và dự án này không cần dùng tới.

## 3. Thu thập, chuẩn hóa, định danh và NLP

Pipeline: **fetch** (ACL XML, arXiv Atom, OpenAlex JSON, tất cả có cache và nhật ký yêu cầu) → **prepare** (chuẩn hóa ID, khử trùng, gán định danh tác giả, phân loại chủ đề, xuất 8 tệp JSONL + manifest có SHA-256) → **validate** (kiểm schema, khóa, khóa ngoại, span chủ đề, checksum) → **import** lên Neo4j.

### Định danh và khử trùng

- Paper: ưu tiên OpenAlex W-id (oa:W…); nếu không khớp dùng acl:&lt;id&gt; hoặc arxiv:&lt;id&gt;. Không gộp theo tiêu đề gần giống; trường hợp mơ hồ ghi vào data/rejected/unresolved.csv.
- Tác giả: chỉ nhận OpenAlex A-id khi số tác giả nguồn bằng số authorship OpenAlex <b>và</b> họ tên ở cùng vị trí tương thích. Ngược lại tác giả nhận ID cục bộ src:&lt;paper&gt;#&lt;vị trí&gt;, chỉ tồn tại trong một bài nên không bao giờ tạo cạnh xuyên bài chỉ vì trùng tên.
- Affiliation: chỉ lấy authorships[].institutions của đúng bài, không dùng last_known_institutions; không suy từ email.
- Citation: chỉ giữ khi cả bài trích dẫn và bài được trích đều nằm trong corpus và khác nhau.

| Chỉ số chuẩn hóa | Giá trị |
|---|---|
| Authorship gán OpenAlex ID đã kiểm (verified) | 5.359 |
| Authorship chỉ theo nguồn (source_only) | 712 |
| Authorship lệch tên với OpenAlex (unresolved) | 27 |
| Bài lệch số tác giả nguồn vs OpenAlex | 4 |
| Authorship verified nhưng không có institution | 1.332 |
| Bài có referenced_works | 333 |
| Bài thiếu abstract | 0 |
| Node Author theo trạng thái | source_only: 712, unresolved: 27, verified: 4.691 |

### Phân loại chủ đề bằng luật

Đầu vào là title + \n + abstract, chuẩn hóa Unicode NFKC, chữ thường, gom khoảng trắng. Mỗi mẫu là một regex có ranh giới từ (ví dụ \brag\b không khớp “fragment”). Khớp ở tiêu đề được 2 điểm, ở abstract 1 điểm (mỗi topic tối đa một lần mỗi trường), ngưỡng 2, tối đa 2 topic; hòa điểm ở vị trí cuối thì không gán topic hòa và đưa vào rà tay. Phiên bản luật: **topics-v1.1** (configs/topics.yaml). Không dùng embedding, mô hình học máy hay API LLM.

| Topic | Số bài gán |
|---|---|
| llm | 328 |
| mt | 25 |
| qa | 24 |
| retrieval | 27 |
| summarization | 26 |
| safety_eval | 21 |
| UNKNOWN (không topic) | 669 |
| tie_review | 0 |

Ví dụ thật từ corpus (span chứng cứ trích nguyên văn):

- [mt] “Attention Link: An Efficient Attention-Based Low Resource Machine Translation Architecture” – span “Machine Translation” (https://arxiv.org/abs/2302.00340)
- [retrieval] “Almanac: Retrieval-Augmented Language Models for Clinical Medicine” – span “Retrieval-Augmented” (https://arxiv.org/abs/2303.01229)
- [llm] “LLMMaps -- A Visual Metaphor for Stratified Evaluation of Large Language Models” – span “Large Language Models” (https://arxiv.org/abs/2304.00457)

Pilot luật: 50 bài đầu tiên theo ID đã được xem trước khi lấy mẫu đánh giá; 18/18 nhãn được gán trong pilot được tác tử đánh giá là hợp lý; 32/50 bài UNKNOWN (luật ưu tiên precision). Sửa duy nhất: thêm mẫu 'speech translation' cho mt (v1.1), sau đó đóng băng luật trước khi lấy mẫu đánh giá.

## 4. Hợp đồng dữ liệu JSONL v1 và schema Neo4j

Thư mục data/processed/ gồm đúng 8 tệp JSONL UTF-8 (mỗi dòng một đối tượng JSON) và manifest.json được ghi cuối cùng. Bộ nạp chỉ chạy khi đủ tệp, đúng schema và đúng checksum.

| Tệp | Số dòng | SHA-256 (16 ký tự đầu) |
|---|---|---|
| papers.jsonl | 1.091 | d214b99a48813f97 |
| authors.jsonl | 5.430 | e915056c0e153db5 |
| institutions.jsonl | 600 | f9778808d4ce0d54 |
| venues.jsonl | 7 | 98f669281a74d49c |
| paper_authors.jsonl | 6.098 | c7e052ca2513979d |
| affiliations.jsonl | 4.764 | 5230f6a6708f2098 |
| citations.jsonl | 26 | a26adef5693b3a12 |
| paper_topics.jsonl | 451 | 5bb54286df21fcc8 |

Ví dụ một dòng papers.jsonl thật (abstract rút gọn):

```
{
 "id": "oa:W4385564926",
 "title": "Multi-Row, Multi-Span Distant Supervision For Table+Text Question Answering",
 "year": 2023,
 "abstract": "Question answering (QA) over tables and linked text, also called TextTableQA, has witnessed significant research in recent years, as tables …",
 "doi": "10.18653/v1/2023.acl-long.449",
 "acl_id": "2023.acl-long.449",
 "arxiv_id": null,
 "source_kind": "acl",
 "source_url": "https://aclanthology.org/2023.acl-long.449/",
 "venue_id": "venue:acl:2023.acl-long",
 "openalex_id": "W4385564926",
 "abstract_origin": "acl"
}
```

### 5 nhãn nút và 10 loại quan hệ

| Nhãn | Số nút |
|---|---|
| Paper | 1.091 |
| Author | 5.430 |
| Institution | 600 |
| Venue | 7 |
| Topic | 6 |

| # | Quan hệ | Cặp nút | Điều kiện / ý nghĩa | Số cạnh | Paper làm chứng |
|---|---|---|---|---|---|
| 1 | FIRST_AUTHOR_OF | Author→Paper | Tác giả đứng tên vị trí 1 trên bài (không khẳng định đóng góp lớn nhất). | 1.091 | 1.091 |
| 2 | OTHER_AUTHOR_OF | Author→Paper | Tác giả đứng tên vị trí > 1. | 5.007 | 1.068 |
| 3 | COAUTHORED_WITH | Author—Author | Hai ID tác giả khác nhau cùng một bài; một cặp vô hướng (min_id,max_id), lưu paper_ids, shared_count. | 16.754 | 1.064 |
| 4 | AFFILIATED_WITH | Author→Institution | Tổ chức khai báo trong authorship của chính bài đó (OpenAlex), không phải nơi làm việc hiện tại. | 4.306 | 936 |
| 5 | APPEARS_IN | Paper→Venue | Volume ACL/EMNLP hoặc arXiv cs.CL (preprint). | 1.091 | 1.091 |
| 6 | HAS_TOPIC | Paper→Topic | Luật title/abstract có span chứng cứ; tối đa 2 nhãn. | 451 | 422 |
| 7 | CITES | Paper→Paper | Paper X trích dẫn Y, cả hai trong corpus, theo referenced_works của X. | 26 | 22 |
| 8 | ORG_COAUTHORED_WITH | Institution—Institution | Hai tổ chức khác nhau do hai tác giả khác nhau khai báo trên cùng một bài. | 2.001 | 554 |
| 9 | RESEARCHES | Author→Topic | Tác giả có ≥ 2 bài khác nhau mang nhãn topic đó trong corpus. | 105 | 112 |
| 10 | ACTIVE_IN | Institution→Topic | Tổ chức có ≥ 2 bài khác nhau (có tác giả khai báo tổ chức) mang topic đó. | 139 | 252 |

Mọi quan hệ lưu source_kind, source_url, evidence_paper_ids, evidence_count, first_year/last_year và build_version. Số quan hệ và số paper làm bằng chứng được báo riêng, không cộng lẫn. Bài có hơn 20 tác giả không sinh clique đồng tác giả mà được đưa vào danh sách rà tay (4 bài).

![Hình 1. Số cạnh duy nhất theo loại quan hệ (snapshot thật).](D:/nlp-collab-graph/output/analysis/relationship_types.png)

*Hình 1. Số cạnh duy nhất theo loại quan hệ (snapshot thật).*

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

## 8. Kết luận, hạn chế và cách tái hiện

Đạt được: pipeline tái hiện được từ nguồn thật tới graph, 10 loại quan hệ có dữ liệu và chứng cứ theo bài, phân tích mạng tác giả với baseline ngẫu nhiên, đánh giá chất lượng có khoảng tin cậy và lưu vết.

- Phép chiếu tác giả bị phân mảnh do lấy mẫu ~1.100 bài trên hàng chục nghìn bài; mạng thật dày hơn nhiều.
- Tác giả không khớp OpenAlex được giữ ở mức một bài (source_only), làm giảm số cạnh xuyên bài nhưng tránh gộp nhầm.
- Citation chỉ là trích dẫn nội bộ corpus, không đo toàn bộ ảnh hưởng học thuật.
- Phân loại chủ đề bằng luật có độ bao phủ hạn chế (nhiều bài UNKNOWN) – chấp nhận để giữ precision.
- ORG_COAUTHORED_WITH là đồng xuất hiện trên bài, không phải thỏa thuận hợp tác; ACTIVE_IN chỉ xét trong corpus.
- Ngưỡng “2000 nghìn nút” chưa được giảng viên xác nhận; precision theo người gán nhãn chưa đo.

Lệnh tái hiện (cần .env với các biến ở mục 5):

```
uv sync
uv run pytest -q
uv run python -m src.cli fetch --config configs/scope.yaml
uv run python -m src.cli prepare --config configs/topics.yaml
uv run python -m src.cli validate --data data/processed
uv run python -m src.cli import --data data/processed --dry-run
uv run python -m src.cli import --data data/processed
uv run python -m src.cli analyze --out output/analysis
uv run python -m src.cli sample --per-type 20 --seed 20261107
uv run python -m src.cli score --labels evaluation/labels.csv
uv run python -m src.cli report --out report/final.pdf
```

Hash manifest: papers.jsonl SHA-256 = d214b99a48813f97c51f5ecbd13ca614d58fae2c48148be0445bf0ad0364605d. Link GitHub: chưa có (repo chỉ ở máy cục bộ).

Tài liệu tham khảo: ACL Anthology (aclanthology.org/faq/api), arXiv API User Manual (info.arxiv.org/help/api), OpenAlex Works/Authorships/Topics (help.openalex.org), Neo4j Python Driver Manual, NetworkX small-world reference.
