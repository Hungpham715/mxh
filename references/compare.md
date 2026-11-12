# So sánh các team — pipeline, GraphRAG, model và mức hoàn thiện

## Kết luận nhanh
Dưới đây là bài tập lớn của các anh chị khóa trước thực hiện, tôi dùng để tham khảo
Nếu mục tiêu là một hệ thống GraphRAG từ câu hỏi đến câu trả lời, thứ tự nổi bật là:

1. **Team 9 — 88/100**: đầy đủ nhất; hybrid vector + graph, LangGraph multi-hop, có fine-tune model trích thực thể.
2. **Team 6 — 83/100**: iterative GraphRAG rõ và có đánh giá; chỉ graph retrieval, không vector, không fine-tune.
3. **Team 5 — 77/100**: query graph có kiểm soát, dễ chống bịa; thiếu vector và training Qwen chưa tái lập.
4. **Team 13 — 75/100**: graph + fine-tune NER/RE tốt, nhưng chatbot GraphRAG chưa nối end-to-end.
5. **Team 7 — 54/100**: crawler/graph vận hành tốt, chưa có AI/RAG.
6. **Team 4 — 52/100**: ETL graph rõ, nhưng quan hệ hợp tác còn heuristic và chưa có AI/RAG.
7. **Team 8 — 41/100**: có dữ liệu EPL nhiều mùa, nhưng còn lỗi schema/đường dẫn và chưa có AI/RAG.

Điểm số này đánh giá **mức sẵn sàng kỹ thuật cho bài toán graph + RAG/AI**, không phải điểm học phần. Vì thang điểm dành 35% cho GraphRAG và AI, các team chỉ làm ETL/graph sẽ thấp dù crawler có thể tốt.

## Thang điểm

| Tiêu chí | Trọng số | Đo điều gì |
|---|---:|---|
| Dữ liệu/crawl | 20 | Nguồn, làm sạch, checkpoint, chống trùng, khả năng chạy lại |
| Thiết kế graph | 20 | Node/edge đúng ngữ nghĩa, thời gian, provenance, query được |
| Query/GraphRAG | 20 | Entity linking, retrieval, multi-hop, context, answer |
| Model/huấn luyện | 15 | Model phù hợp, pipeline train có bằng chứng và tái lập |
| Kỹ thuật vận hành | 15 | Cấu hình, secret, test, orchestration, API |
| Đánh giá | 10 | Dataset, metric, baseline, phân tích lỗi |
| **Tổng** | **100** | |

## Bảng điểm chi tiết

| Team | Data /20 | Graph /20 | Query-RAG /20 | AI-train /15 | Kỹ thuật /15 | Eval /10 | Tổng |
|---|---:|---:|---:|---:|---:|---:|---:|
| 9 | 18 | 18 | 19 | 14 | 11 | 8 | **88** |
| 6 | 19 | 17 | 18 | 9 | 10 | 10 | **83** |
| 5 | 16 | 17 | 16 | 12 | 9 | 7 | **77** |
| 13 | 18 | 18 | 5 | 14 | 10 | 10 | **75** |
| 7 | 18 | 15 | 3 | 0 | 13 | 5 | **54** |
| 4 | 17 | 14 | 4 | 0 | 11 | 6 | **52** |
| 8 | 14 | 13 | 2 | 0 | 7 | 5 | **41** |

## So sánh kiến trúc/pipeline

| Team | Nguồn vào | Pipeline graph | Kho graph | Đầu ra chính |
|---|---|---|---|---|
| 4 | Wikipedia API/HTML, seed nghệ sĩ/thể loại | crawl → parse infobox/link → NetworkX | File GEXF/GraphML/JSON | truy vấn Python, network export |
| 5 | Wikipedia XML dump/wikitext | stream parse → Person–Film → cộng tác → CSV | Neo4j + NetworkX | FastAPI answer + trace từng bước |
| 6 | Wikidata SPARQL + Wikipedia text | discovery → extract/filter → Neo4j → Gemini enrichment | Neo4j | web chatbot GraphRAG |
| 7 | Wikipedia, seed bóng đá | BFS crawl → parse/filter → entity/edge → checkpoint | JSON/graph, có thể Neo4j theo báo cáo | shortest path/analytics |
| 8 | Wikipedia 5 mùa EPL | season → club → player/coach → relation CSV | Neo4j + NetworkX | graph/query script |
| 9 | Wikipedia chính trị gia | crawl/BFS → normalize → KG → enrich → vector index | Neo4j + vector indexes | TF/MCQ GraphRAG |
| 13 | Wikidata CSV + Wikipedia text | node/edge CSV → Neo4j; Qwen NER/RE enrichment | Neo4j/AuraDB | analytics, dataset chatbot/eval |

## So sánh component GraphRAG

| Component | T4 | T5 | T6 | T7 | T8 | T9 | T13 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Natural-language API/UI | Không | Có | Có | Không | Không | Có | Chưa tích hợp |
| Entity extraction | Không | Heuristic/NLP | Qwen | Không | Không | Qwen fine-tuned | Qwen fine-tuned cho enrichment |
| Entity linking | Không | Exact/token/fuzzy | Neo4j full-text + fuzzy | Không | Không | model + Neo4j query | Chưa có trong chatbot |
| Intent routing | Không | Regex | Prompt/logic | Không | Không | FAISS semantic router | Chưa có runtime |
| Graph retrieval | Hàm Python | Cypher cố định/n-hop | 1-hop + shortest path | Shortest path | Query cố định | Cypher theo pattern | Analytics/query script |
| Vector retrieval | Không | Không | Không | Không | Không | **Có, BGE-M3** | Không |
| Multi-hop có vòng lặp | Không | Chuỗi quan hệ cố định | **Có, tối đa 5 vòng** | Không | Không | **Có, LangGraph** | Không |
| LLM tạo answer | Không | Qwen2.5-0.5B | Qwen3-0.6B | Không | Không | Qwen2.5-0.5B/Ollama | Qua hệ thống ngoài/eval |
| Citation/provenance trong answer | Không | Không | Chưa cấu trúc | Không | Không | Chưa đầy đủ | Không có runtime |

## Ba kiểu RAG đáng phân biệt

### Team 5: graph-first, deterministic

Question → luật nhận diện intent → hàm Cypher đã định nghĩa → graph facts → Qwen viết lại.

Ưu điểm: dễ kiểm soát, ít nguy cơ sinh Cypher nguy hiểm, dễ biết câu hỏi nào được hỗ trợ. Nhược điểm: regex khó bao phủ cách hỏi mới; không tìm được câu liên quan theo ngữ nghĩa.

### Team 6: iterative graph-only

Question → Qwen tìm entity → lấy 1-hop/path từ Neo4j → Qwen kiểm tra đủ → tìm thêm entity → lặp → answer.

Ưu điểm: phù hợp câu hỏi cần nối nhiều người/phim. Nhược điểm: context có thể phình; model nhỏ vừa chọn entity vừa quyết định dừng; không có vector fallback.

### Team 9: hybrid vector + graph

Question → semantic router → Qwen entity/relation JSON → top-k vector docs → Cypher multi-hop → LangGraph lặp → gộp hai context → TF/MCQ answer.

Ưu điểm: vector search cứu trường hợp từ ngữ không trùng chính xác, graph giữ logic quan hệ. Nhược điểm: nhiều service/phần di động hơn, khó vận hành; answer format còn giới hạn.

## So sánh model và training

| Team | Model | Dùng để làm gì | Có train/fine-tune trong repo? |
|---|---|---|---|
| 4 | Không | — | Không |
| 5 | Qwen2.5-0.5B-Instruct + LoRA artifact; SetFit MiniLM | viết lại answer; phân loại relation | SetFit có code train; Qwen chỉ có artifact/checkpoint, thiếu script train |
| 6 | Qwen3-0.6B; Gemini 2.5 Flash | query-time reasoning/answer; offline extraction | Không, cả hai chạy inference |
| 7 | Không | — | Không |
| 8 | Không | — | Không |
| 9 | Qwen2.5-0.5B QLoRA; BGE-M3; Gemini | entity/relation JSON; embedding; sinh data/đối chứng | Có artifact + mô tả tham số, nhưng thiếu script train hoàn chỉnh |
| 13 | Qwen2.5-0.5B-Instruct LoRA; Gemini | NER/RE enrichment; sinh dataset | **Có notebook train Qwen NER/RE**, 691/102/103 mẫu sau lọc |

Điểm hay nhất của Team 13 là notebook train thật, có LoRA config, trainer và kết quả test loss. Nhưng model đó làm NER/RE cho dữ liệu Nobel; nó chưa phải model text-to-Cypher hoặc answer generator.

## Input/output chuẩn của một luồng tốt

Dùng chung để đọc các report team:

| Giai đoạn | Input nên rõ | Output nên rõ |
|---|---|---|
| User | question:str | request_id |
| Entity extraction | question | {entities:list, relations:list, confidence:float} |
| Entity linking | entity text | node_id, canonical_name, score |
| Vector retrieval | query embedding:list[float] | list[Document] có score/source |
| Graph retrieval | node IDs + relation plan | subgraph:list[dict], Cypher, params |
| Context builder | documents + subgraph | context:str có giới hạn token |
| Generator | question + context | answer:str |
| Evidence | node/edge/document đã dùng | citations:list[dict] |
| Trace | thời gian/trạng thái từng bước | steps:list[object] |

Team 5 làm tốt phần trace; Team 9 làm tốt state multi-hop; Team 6 làm tốt path context. Chưa team nào trả provenance/citation hoàn chỉnh tới người dùng.

## So sánh side problem crawl/data

| Team | Điểm tốt | Rủi ro chính |
|---|---|---|
| 4 | nhiều chế độ seed, retry/rate limit | link Wikipedia bị hiểu nhầm là collaboration |
| 5 | đọc XML dump dạng stream, graph Person–Film rõ | notebook lớn, infobox CSV quá rộng |
| 6 | kết hợp Wikidata và full text, có bước normalize LLM output | nhiều file trung gian thủ công, quota Gemini, credential |
| 7 | checkpoint/resume, signal và memory monitoring | gender default gây bias; số node trong report không thống nhất |
| 8 | edge theo season | CSV trùng cột Location, sai data/node(s), parser dễ gãy |
| 9 | normalization và ontology phong phú | BFS lan phạm vi, LLM edge cần provenance |
| 13 | AwardStatement mô hình hóa đúng | importer xóa toàn DB; projection có mật độ edge bất thường |

## Xếp hạng theo mục tiêu riêng

- **GraphRAG hoàn chỉnh nhất:** Team 9.
- **GraphRAG dễ giải thích và kiểm soát nhất:** Team 5.
- **Suy luận nhiều hop thuần graph rõ nhất:** Team 6.
- **Pipeline fine-tune LLM có code đầy đủ nhất:** Team 13.
- **Crawler có khả năng chạy dài/resume tốt nhất:** Team 7.
- **Schema thời gian theo mùa dễ hiểu nhất:** Team 8.
- **ETL graph đơn giản, dễ học nhất:** Team 4.

## Ưu tiên cải thiện

1. Team 9: sửa router gate, tham số hóa Cypher, lazy-init service, thêm open QA và citation.
2. Team 6: trả evidence có cấu trúc, giới hạn context theo budget, thay parser “ĐỦ/CHƯA ĐỦ” bằng JSON schema.
3. Team 5: nối use_finetuned thật sự, thêm training script Qwen và vector fallback; bỏ bộ lọc từ khóa chống bịa quá thô.
4. Team 13: nối dataset text-to-Cypher thành runtime; sandbox/allowlist Cypher; thay destructive import bằng chế độ rõ môi trường.
5. Team 7: chuẩn hóa schema code/report, sửa bias giới tính, thêm entity linking + API.
6. Team 4: xác minh collaboration bằng bằng chứng và bổ sung Neo4j importer nếu đó là kiến trúc mục tiêu.
7. Team 8: sửa CSV/path/secret trước, thêm validation và GDS/query layer sau.

## Ghi chú phương pháp

Phân tích dựa trên snapshot repo ở commit ghi trong từng file và các báo cáo được cung cấp. Khi code và report mâu thuẫn, kết luận ưu tiên hành vi thể hiện trong code/artifact; số liệu chỉ có trong report được ghi rõ là số do báo cáo nêu.

