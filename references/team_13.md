# Team 13 — Knowledge graph Nobel và pipeline fine-tune NER/RE

## Kết luận nhanh

Repo có nền knowledge graph tốt, có phân tích mạng và có notebook fine-tune Qwen2.5-0.5B để bóc thực thể/quan hệ từ văn bản Nobel. Repo cũng tạo dataset câu hỏi→Cypher và bộ câu hỏi trắc nghiệm. Tuy nhiên chưa có runtime GraphRAG hoàn chỉnh nối user query → model sinh Cypher → Neo4j → LLM trả lời; phần “chatbot pipeline” hiện chủ yếu là tạo dataset và đánh giá Dify/Gemini.

- Repo: https://github.com/tlam25/network-of-awards-and-winners
- Commit đã đọc: c51909a3634773b0bb76710d4029053173ab311e
- Nguồn đối chiếu: code, notebook có output đã lưu, CSV/JSON, README.

## Kiến trúc

Có bốn pipeline:

1. Xây graph nền: Wikidata/SPARQL → allNobel.csv → node/edge CSV → Neo4j.
2. Làm giàu graph: Wikipedia text → dữ liệu NER/RE → fine-tune Qwen → trích entity/relation → hậu xử lý → Neo4j.
3. Phân tích mạng: Neo4j → NetworkX projection → small-world, ranking, Louvain.
4. Dữ liệu chatbot: Neo4j schema/sample → Gemini sinh câu hỏi/Cypher hoặc MCQ → chia train/val/test → đánh giá ngoài repo.

Điểm quan trọng: model Qwen được train để trích tri thức cho graph, không phải bằng chứng rằng chatbot text-to-Cypher đã được train.

## Node và edge

| Node | Ý nghĩa |
|---|---|
| Person | Người/tổ chức đoạt Nobel |
| Award | Hạng mục Nobel |
| AwardStatement | Một lần nhận giải cụ thể, giữ year và motivation |
| Country | Quốc tịch/quốc gia |
| Occupation | Nghề nghiệp |
| Field | Lĩnh vực |
| Organization | Trường/tổ chức |
| Position | Chức vụ |

| Edge | Ý nghĩa |
|---|---|
| RECEIVED | Person nhận AwardStatement |
| IS_INSTANCE_OF | AwardStatement thuộc Award |
| IS_CITIZEN_OF | Person có quốc tịch |
| WORKS_AS | Person có nghề |
| WORKS_IN_FIELD | Person làm trong lĩnh vực |
| EDUCATED_AT / EMPLOYED_BY / MEMBER_OF | Học/làm/thành viên tổ chức |
| HOLDS_POSITION | Giữ chức vụ |

Ví dụ thật:

    Person.csv:
    Q102250, Peter Agre, ...

    AwardStatement.csv:
    name = Q102250_2003
    year = 2003
    motivation = "..."

    Relations.csv:
    Peter Agre --RECEIVED--> Q102250_2003
    Q102250_2003 --IS_INSTANCE_OF--> Nobel Prize in Chemistry

Tách AwardStatement là quyết định tốt: năm và lý do trao giải thuộc “sự kiện nhận giải”, không phải thuộc tính cố định của Person hay Award.

## Pipeline graph nền và input/output

| Bước | Input | Xử lý | Output |
|---|---|---|---|
| Truy vấn nguồn | SPARQL Wikidata | lấy laureate và thuộc tính | allNobel.csv |
| Tạo node | mỗi row CSV kiểu dict[str,str] | gom theo loại và khử trùng | Person.csv, Award.csv, Country.csv… |
| Tạo lần nhận giải | person_id + year + motivation | ID ghép person_year | AwardStatement.csv |
| Tạo edge | các trường trong row | map sang relation type | Relations.csv |
| Import | CSV | constraint/MERGE Cypher | Neo4j/AuraDB |
| Phân tích | Neo4j records | project sang NetworkX | metric và ảnh |

extract_from_wikidata_to_csv.py có tên dễ hiểu nhầm: code thực tế đọc allNobel.csv đã có sẵn rồi mới sinh CSV import, không trực tiếp gọi endpoint SPARQL trong luồng chạy đó.

Import script có câu xóa toàn bộ graph và xóa constraints trước khi nạp. Đây là thao tác phá hủy dữ liệu; chỉ nên chạy trên database riêng sau backup và xác nhận môi trường.

## Pipeline làm giàu bằng AI

1. Crawl/đọc Wikipedia text của laureate.
2. Chuẩn bị sample có name:str, text:str, entities:list và relations:list.
3. Lọc sample dài hơn 1.536 token; loại training sample không có relation.
4. Format thành prompt yêu cầu output JSON {entities, relations}.
5. Fine-tune Qwen bằng LoRA.
6. Dùng model đã fine-tune chạy NER/RE trên văn bản mới.
7. Hậu xử lý JSON: chuẩn tên/type, khử trùng, loại quan hệ lỗi.
8. Import node/edge mới vào Neo4j.

Kiểu output mong đợi:

    {
      "entities": [
        {"id": "E1", "name": "Peter Agre", "type": "Person"},
        {"id": "E2", "name": "Johns Hopkins University", "type": "Organization"}
      ],
      "relations": [
        {"head": "E1", "type": "EMPLOYED_BY", "tail": "E2"}
      ]
    }

## Model AI và cách train

Notebook ptich-mxh-finetuned-nobel-kg-extraction.ipynb chứa pipeline train thật và output đã lưu:

- Base model: Qwen/Qwen2.5-0.5B-Instruct.
- Dataset: trangpt666/nobel_laureates_extraction.
- Trước lọc: train 817, validation 102, test 103.
- Sau lọc sample train phải có relation: train 691; validation 102; test 103.
- Mỗi sample nối prompt + JSON chuẩn + EOS; tối đa 1.536 token.
- LoRA: r=8, alpha=16, dropout=0,05; target q/k/v/o/gate/up/down projection.
- Train batch 1, gradient accumulation 16 → batch hiệu dụng 16.
- 10 epoch, learning rate 3e-4, 50 warmup steps; fp16 và gradient checkpointing.
- Đánh giá mỗi epoch, lưu theo epoch, chọn model có eval_loss thấp nhất; có early stopping.
- Output notebook ghi test eval_loss 0,4995 và perplexity 1,6480.
- Cuối pipeline lưu LoRA, có bước merge LoRA vào base model và tham chiếu model trangpt666/qwen25-05B-instruct-nobel-kg-v2.

Giới hạn đánh giá: eval loss/perplexity chỉ đo khả năng dự đoán token, chưa trực tiếp cho biết entity/relation đúng bao nhiêu. Cần precision/recall/F1 theo entity và triple, đặc biệt exact match cho head–relation–tail.

## Dataset chatbot và luồng query→answer thực tế

Repo tạo hai loại dataset:

- nobel_cypher_finetune_data_with_splits.csv có question, hops, cypher_query, thinking, context, split.
- Bộ MCQ tiếng Việt do Gemini sinh và tăng cường.

Ví dụ một row text-to-Cypher:

    input:
    question:str = "..."
    hops:int = 4

    target:
    cypher_query:str = "MATCH ... RETURN ..."
    thinking:str = "..."
    split:str = "train"

Luồng mong muốn là câu hỏi → model text-to-Cypher → chạy Neo4j → context → LLM answer. Nhưng trong snapshot:

- có code sinh dataset và chia tập;
- có eval_dify.py/eval_gemini.py gọi hệ thống ngoài;
- không có model text-to-Cypher được train/đóng gói;
- không có API/chat UI nối trọn luồng;
- không có vector index/embedding retrieval cho chatbot.

Vì vậy repo chưa có một luồng user query→answer nội bộ để mô tả như sản phẩm chạy được. Qwen fine-tuned ở trên phục vụ NER/RE enrichment, không tự động biến thành chatbot.

## Graph analysis

Code project Neo4j sang NetworkX rồi chạy:

- small-world;
- ranking/centrality;
- community detection Louvain;
- shortest path.

Output lưu trong analysis_algorithm/output. Kết quả snapshot ghi khoảng 1.022 node và 277.924 edge trên projection, average path length 1,4959, clustering 0,8582, 28 community và modularity 0,1236. Mật độ edge rất cao cần kiểm tra projection có tạo clique theo shared attributes hay đếm cạnh lặp hay không.

## Vấn đề crawl/vận hành

- Wikipedia/Wikidata có redirect, tên nhiều ngôn ngữ và thiếu trường.
- NER/RE generative có thể tạo JSON không hợp lệ hoặc relation ngoài ontology.
- Cần lưu provenance cho mỗi edge: URL, đoạn văn, model version, confidence.
- Script import xóa DB là rủi ro lớn.
- Hai pipeline “NER/RE enrichment” và “chatbot text-to-Cypher” đang tách rời; tài liệu nên nói rõ artifact nào thuộc pipeline nào.
- eval_gemini.py có lỗi cú pháp trong snapshot, cần sửa trước khi chạy.

## Đánh giá

**75/100**. Graph model và pipeline fine-tune NER/RE có bằng chứng tốt; AwardStatement là thiết kế dữ liệu đúng. Điểm trừ vì chatbot/GraphRAG chưa tích hợp end-to-end, đánh giá model mới dừng ở loss/perplexity và import có thao tác phá hủy nguy hiểm.

## Bằng chứng code chính

- build_db/src/extract_from_wikidata_to_csv.py, import_to_auradb.py.
- graph_augmentation/src/ptich-mxh-finetuned-nobel-kg-extraction.ipynb.
- graph_augmentation/src/preprocess_ner_re_finetune_data.py, extraction_ner_re_finetune_data.py, postprocess.py.
- chatbot_pipeline/create_dataset_chatbot_pipeline/.
- analysis_algorithm/src/.
- shortest-path-nobel-network/src/find-shortest-path.py.

