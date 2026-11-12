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
