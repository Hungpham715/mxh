# Team 9 — Hybrid GraphRAG chính trị gia Việt Nam

## Kết luận nhanh

Đây là repo hoàn chỉnh nhất về RAG trong nhóm được phân tích. Hệ thống kết hợp hai đường truy xuất: vector search để tìm đoạn liên quan theo ngữ nghĩa và Neo4j để đi theo quan hệ nhiều hop. LangGraph điều phối vòng lặp; Qwen đã fine-tune nhận diện thực thể/quan hệ. Hạn chế lớn là chatbot chỉ xử lý câu Đúng/Sai và trắc nghiệm, chưa phải hỏi đáp mở.

- Repo: https://github.com/datmieu204/political-net
- Commit đã đọc: 368ab41328a3d4bc81573acf2167c403b3d880b2
- Nguồn đối chiếu: code, artifact model/data, Slide_Nhóm_9.pdf và Report_Nhóm_9.pdf.

## Kiến trúc

Có ba lớp:

1. **Dữ liệu/graph**: crawl Wikipedia → làm sạch dữ liệu → dựng JSON/Cypher → lưu tri thức có cấu trúc trong Neo4j.
2. **Chuẩn bị AI**: tóm tắt trang chính trị gia → tạo đoạn văn và vector ngữ nghĩa → fine-tune Qwen để nhận diện thực thể.
3. **GraphRAG lúc hỏi**: phân loại câu hỏi → bóc thực thể → tìm theo vector và đi graph nhiều bước → gộp bằng chứng → Qwen trả lời.

Luồng ngắn gọn:

Wikipedia → infobox/text → normalize → knowledge graph → Neo4j  
Text summary/edge text → BGE-M3 embedding → Neo4j vector indexes  
Question → LangGraph → entity JSON → vector docs + Cypher subgraph → multi-hop loop → final answer

## Node và edge

| Node | Ý nghĩa |
|---|---|
| Politician | Chính trị gia |
| Position | Chức vụ |
| Location | Nơi sinh/nơi mất |
| Award | Huân/huy chương |
| MilitaryCareer, MilitaryRank, Campaigns | Sự nghiệp quân sự |
| AlmaMater, AcademicTitle | Trường học/học hàm |
| TermPeriod | Nhiệm kỳ |

| Edge | Ý nghĩa |
|---|---|
| PRECEDED / SUCCEEDED | Tiền nhiệm/kế nhiệm |
| BORN_AT / DIED_AT | Nơi sinh/mất |
| SERVED_AS | Giữ chức vụ, có thời gian/trạng thái |
| ALUMNUS_OF | Học tại |
| HAS_RANK | Có quân hàm |
| AWARDED | Được trao giải |
| SERVED_IN / FOUGHT_IN | Phục vụ/tham chiến |

Ví dụ thật trong knowledge_graph_sample.json:

    node:
    {
      "id": "pol19498354",
      "type": "Politician",
      "name": "Ngô Văn Tuấn",
      "properties": {"birth_date": "1971-08-02", "party": "Đảng Cộng sản Việt Nam"}
    }

    edge:
    {
      "from": "pol19498354",
      "to": "pos...",
      "type": "SERVED_AS",
      "properties": {
        "term_start": "2022-10-21",
        "term_end": "nay",
        "status": "bị cách chức",
        "reason": "..."
      }
    }

Việc đưa nhiệm kỳ/trạng thái vào property của edge SERVED_AS là hợp lý: đây là dữ liệu của quan hệ giữ chức, không phải thuộc tính vĩnh viễn của một người. Báo cáo nêu graph sau làm giàu có 6.223 node và 16.807 edge.

## Pipeline dữ liệu offline

| Bước | Input | Xử lý | Output |
|---|---|---|---|
| Lấy danh sách | các khóa Quốc hội/trang danh sách | Crawl tên chính trị gia | list[str] tên/URL |
| Crawl trang | URL Wikipedia | lấy HTML/wikitext/infobox | text và dict thô |
| Làm sạch | key/value infobox | chuẩn ngày, tên trường, chức vụ | dict chuẩn hóa |
| Mở rộng | seed + link liên quan | BFS, chống lặp | thêm thực thể |
| Dựng KG | các dict | tạo node/edge, ID | knowledge_graph.json và Cypher |
| Import | JSON/Cypher | MERGE vào Neo4j | graph có cấu trúc |
| Tóm tắt | intro/full text | Qwen/Gemini sinh summary | full_text_summary:str |
| Embedding | summary và text mô tả edge | BAAI/bge-m3 → vector số thực | list[float] gắn vào node/chunk |
| Tạo index | vector trong Neo4j | index politician và relation chunk | hai vector index dùng lúc hỏi |

Side problem quan trọng:

- Wikipedia thiếu hoặc không thống nhất infobox; parser phải xử lý alias key và giá trị nhiều dòng.
- BFS dễ crawl lan sang nhân vật không thuộc phạm vi chính trị.
- Chuẩn hóa tên/chức vụ và khoảng thời gian “nay” quyết định graph có nối đúng hay không.
- LLM enrichment có thể sinh quan hệ không có trong nguồn; nên lưu URL, đoạn trích và confidence cho từng edge.

## Model AI và cách train

### Model nhận diện thực thể/quan hệ

Nhóm thử PhoBERT theo kiểu gắn nhãn từng token, nhưng báo cáo cho biết mô hình khó nhận các thực thể dài. Pipeline cuối chuyển sang Qwen2.5-0.5B dạng sinh JSON.

- Dữ liệu: 30.000 câu sinh từ graph và 3.000 câu tăng cường bằng Gemini theo báo cáo.
- Mỗi mẫu có question:str và answer_json. Output JSON chứa entities và intent_relation.
- Ví dụ kiểu dữ liệu:

    {
      "question": "Ai là người kế nhiệm ...?",
      "answer_json": {
        "entities": [{"text": "Nguyễn Hữu Thọ", "type": "Politician"}],
        "intent_relation": ["SUCCEEDED"]
      }
    }

- Base: unsloth/qwen2.5-0.5b-unsloth-bnb-4bit.
- Cách train: supervised fine-tuning kết hợp QLoRA. Model nền lưu 4-bit để giảm VRAM; LoRA chỉ học các ma trận nhỏ.
- LoRA: r=16, alpha=16, dropout=0; tác động các projection q/k/v/o và gate/up/down.
- Batch vật lý 2, cộng dồn gradient 8 → batch hiệu dụng 16; tối đa 2.048 token; AdamW 8-bit, lịch learning rate tuyến tính và 100 bước warmup theo báo cáo.
- Prompt theo dạng system + user + assistant JSON; loss tập trung vào phần assistant theo báo cáo.
- Artifact model có trong chatbot/ner và được phục vụ bằng Ollama với tên qwen-ner-0.5b-v2:latest.

Điểm tái lập còn thiếu: snapshot không có notebook/script train tương ứng, nên tham số chủ yếu được xác nhận từ report và adapter artifact, không thể chạy lại một lệnh từ raw data đến model.

### Model embedding và model trả lời

- BAAI/bge-m3 biến text thành list[float]; vector gần nhau biểu diễn nội dung gần nghĩa.
- Qwen2.5:0.5b qua Ollama dùng để tóm tắt context và tạo đáp án.
- Gemini chủ yếu hỗ trợ sinh dữ liệu/đối chứng, không phải model duy nhất lúc chạy chatbot.

## Luồng user query → answer, chi tiết input/output

Ví dụ câu Đúng/Sai: “Nguyễn Hữu Thọ từng giữ chức Chủ tịch Quốc hội.”

1. serve_app.py nhận user_input:str và gọi LangGraph đã compile.
2. intent_node dùng semantic router: embedding câu hỏi → FAISS → politician_tf, politician_mpc hoặc out_of_scope.
3. Code đồng thời hỏi hai Neo4j vector index để kiểm tra độ liên quan. Tuy nhiên nhánh quyết định cuối gần như vẫn trả intent của router; ngưỡng graph 0,9 chưa thật sự chặn được câu ngoài miền.
4. extract_entities_node gọi model NER Qwen. Output:

       {
         "entities": [{"text": "Nguyễn Hữu Thọ", "type": "Politician"}],
         "intent_relation": ["SERVED_AS"]
       }

5. retrieval_node chạy song song về mặt logic:
   - politician_vector_index.similarity_search(user_msg, k=5) → list Document về node;
   - relationchunk_vector_index.similarity_search(user_msg, k=5) → list Document về edge.
6. retrieval_summary_node nén 10 document thành retrieval_summary:str.
7. init_multihop_node đọc entity, relation và keyword để chọn pattern: simple, chain, path, comparison, aggregation hoặc explore; đặt max_hops và plan_steps.
8. multihop_query_generator_node tạo Cypher theo hàm quan hệ/pattern; output cypher_query:str.
9. multihop_execute_node gửi Cypher tới Neo4j; output subgraph:list[dict].
10. multihop_analyze_node tóm tắt kết quả, ghi reasoning_steps, phát hiện tên/quan hệ mới và quyết định needs_more_hops:bool. Nếu chưa đủ và chưa đạt max_hops, quay lại bước 8.
11. multihop_finalize_node tạo graph_summary:str.
12. combine_context_node ghép retrieval_summary + graph_summary thành combined_context:str.
13. Với câu Đúng/Sai, tf_answer_node trả verdict và giải thích. Với trắc nghiệm, mpc_parse_options_node tách A/B/C/D rồi mpc_answer_node chọn đáp án.
14. state cuối có assistant_output:str để giao diện hiển thị.

State đi qua pipeline còn giữ hop_count, discovered_entities, explored_relations và accumulated_context, nên có thể debug từng vòng.

## RAG component

| Thành phần | Cách triển khai |
|---|---|
| Router | FAISS trên các câu ví dụ |
| Entity/relationship extraction | Qwen fine-tuned sinh JSON |
| Vector retrieval | Neo4jVector + BGE-M3, top 5 node và top 5 edge chunk |
| Graph retrieval | Cypher theo relation/pattern |
| Multi-hop | LangGraph loop query → execute → analyze |
| Context fusion | Ghép summary vector và graph |
| Generation | Qwen qua Ollama |
| Output | Chỉ Đúng/Sai hoặc trắc nghiệm; chưa có open QA |

## Kết quả và rủi ro

Artifact đánh giá trong repo cho thấy local combined accuracy 45,33%, Gemini 60,50%; MCQ local 45,12% so với Gemini 75,20%; TF của hai bên khoảng 45,80%. Các số này cho thấy kiến trúc tốt nhưng chất lượng answer model còn yếu.

Rủi ro chính:

- nodes.py khởi tạo driver, embedding và vector stores ngay khi import; startup sẽ thất bại nếu Neo4j/Ollama chưa sẵn sàng.
- Mật khẩu Neo4j local xuất hiện trong config.
- Cypher được ghép chuỗi ở nhiều nhánh; escape hiện chưa đủ mạnh cho input đối nghịch.
- Router check graph có logic chưa chặt.
- crawl/show_xml_structure.py có lỗi cú pháp.
- Thiếu một lệnh end-to-end tái tạo data, index và model.

## Đánh giá

**88/100**. Mạnh nhất về kiến trúc hybrid retrieval, state nhiều hop và model NER chuyên biệt. Điểm trừ vì chatbot giới hạn dạng câu hỏi, accuracy còn thấp, training chưa tái lập trọn vẹn và vận hành phụ thuộc nhiều service khởi tạo cùng lúc.

## Bằng chứng code chính

- preprocessing/, crawler/ và algorithm/graph_builder.py: ETL/KG.
- chatbot/core/vector_index.py: embedding/index.
- chatbot/graph/state.py, graph.py, nodes.py: LangGraph.
- chatbot/entity_identification/train_data/: mẫu train.
- chatbot/ner/qwen2.5-0.5b_ner_model/: artifact model.
- serve_app.py: điểm vào chatbot.
