# Team 6 — GraphRAG mạng diễn viên/đạo diễn Mỹ

## Kết luận nhanh

Repo có pipeline GraphRAG lặp tương đối rõ: Qwen tìm thực thể, Neo4j lấy node/edge và đường đi, Qwen kiểm tra thông tin đã đủ chưa; nếu chưa, hệ thống tìm thêm thực thể rồi truy xuất lại. Đây là GraphRAG thật nhưng không có vector retrieval và Qwen được dùng ở chế độ suy luận, không có fine-tune trong repo.

- Repo: https://github.com/giakhanh22024558/Social-Network-Analysis
- Nhánh/commit đã đọc: master — e2c636989afa949d5dd669f35e2b963751a547a7
- Nguồn đối chiếu: code, notebook đánh giá, slide và báo cáo Team 6.

## Kiến trúc

Gemini và Qwen làm hai việc khác nhau:

- Gemini 2.5 Flash chạy offline để bóc thêm thực thể/quan hệ từ nội dung Wikipedia.
- Qwen3-0.6B chạy lúc người dùng hỏi để tìm tên, đánh giá đủ/chưa đủ và viết câu trả lời.

Luồng tổng quát: Wikidata/Wikipedia → JSON người/phim → Neo4j nền. Song song, full text Wikipedia → Gemini bóc tri thức → JSON sạch → làm giàu Neo4j. Khi hỏi: câu hỏi → Qwen tìm tên → Neo4j trả context/đường đi → Qwen kiểm tra đủ chưa → nếu chưa thì tìm thêm → Qwen trả lời.

Không nên gọi bước Gemini là “train Qwen”: repo không có kết nối huấn luyện như vậy.

## Graph node và edge

Graph nền có Person và Film; bước làm giàu bổ sung địa điểm, giải thưởng, tổ chức, trường học…

| Node/edge | Ý nghĩa | Ví dụ dạng dữ liệu |
|---|---|---|
| Person | Diễn viên/đạo diễn | {qid: "Q2071", name: "David Lynch", birthDate: "1946-01-20"} |
| Film | Phim | {qid: "...", name: "..."} |
| ACTED_IN | Người đóng phim | Person → Film |
| DIRECTED | Người đạo diễn phim | Person → Film |
| Node mở rộng | Location, Award, Organization, University/School | object có id, label |
| Edge mở rộng | BORN_IN, EDUCATED_AT, FOUNDED, COLLABORATED_WITH, WORKED_FOR, WON_AWARD | triple {head, type, tail} |

Ví dụ thật trong all_actors_extracted.json:

    {
      "David Lynch_Q2071": {
        "summary": "...",
        "entities": [{"id": "...", "label": "..."}],
        "relationships": [{"head": "David Lynch", "type": "BORN_IN", "tail": "Missoula"}]
      }
    }

Báo cáo nêu graph có 9.324 node và 17.054 edge; một bảng khác ghi 17.254 edge, nên cần chạy phép đếm trên bản Neo4j cuối để chốt số.

## Pipeline offline và kiểu dữ liệu

Repo đánh số script theo thứ tự thực thi:

| Bước | Input | Output | Vai trò |
|---|---|---|---|
| 1_run_discovery.py | năm, giới tính, câu SPARQL | danh sách QID kiểu list[str] | Tìm người từ Wikidata |
| 2_run_extraction.py | QID | JSON map người/phim | Lấy thuộc tính có cấu trúc |
| 3_filter_actors.py | JSON thô | JSON đã lọc | Loại đối tượng không phù hợp |
| 4_import_to_neo4j.py | JSON | node/edge Neo4j | Tạo graph nền |
| 6_get_content_data.py | tên/QID | full text Wikipedia kiểu str | Lấy văn bản giàu thông tin |
| 7_process_contentdata_llm.py | văn bản | {summary, entities, relationships} | Gemini bóc tri thức |
| 8_process_LLM_data.py | JSON LLM | JSON chuẩn hóa/khử trùng | Giảm rác và trùng |
| 9_import_enrich_data.py | JSON sạch | node/edge mới | Làm giàu Neo4j |

Tên file giữa một số bước chưa nhất quán và thiếu script số 5. Pipeline phải chạy tay qua các file trung gian, chưa có orchestrator kiểm tra input trước mỗi bước, nên dễ dùng nhầm đường dẫn hoặc phiên bản JSON.

## Luồng user query → answer

Implementation rõ nhất là chatbot/4_iterative_graph_rag.py.

Ví dụ: “Jon Voight có quan hệ gì với Angelina Jolie?”

1. Input là question:str.
2. Qwen nhận prompt có ví dụ, trả một dòng tên riêng; parser biến thành list[str], ví dụ ["Jon Voight", "Angelina Jolie"].
3. normalize_entities so tên với toàn bộ n.name đã cache từ Neo4j, ngưỡng fuzzy 85; output là danh sách tên chuẩn.
4. get_full_graph_context tìm từng node, lấy thuộc tính cá nhân, quan hệ trực tiếp 1 hop và đường đi ngắn nhất giữa từng cặp, tối đa 6 hop. Output là một chuỗi context.
5. Qwen nhận {question, context}, trả text “ĐỦ” hoặc “CHƯA ĐỦ”. Parser dùng kiểm tra chuỗi để chuyển thành bool.
6. Nếu chưa đủ, Qwen đề xuất thêm tên cần tìm; tên mới được hợp vào set rồi quay lại bước 3–5. Tối đa 5 vòng.
7. Cuối cùng Qwen nhận câu hỏi + toàn bộ context và sinh answer:str.
8. Backend FastAPI có POST /chat; websocket /ws/chat stream log, trạng thái và kết quả về giao diện.

## GraphRAG component

| Thành phần | Có? | Ghi chú |
|---|---:|---|
| Entity extraction | Có | Qwen sinh danh sách tên |
| Entity linking | Có | Full-text Neo4j + fuzzy matching |
| Graph retrieval | Có | Thuộc tính, 1-hop, shortest path tối đa 6 hop |
| Lặp nhiều bước | Có | Qwen đánh giá đủ/chưa đủ, tối đa 5 vòng |
| Vector retrieval | Không | Không có embedding hay vector index trong chatbot |
| Generator | Có | Qwen3-0.6B |
| Answer evidence | Một phần | Context có đường đi nhưng API chưa trả node/edge/evidence URL cụ thể |

## Model AI và cách train

- Qwen/Qwen3-0.6B được tải trực tiếp bằng Transformers. Không có script fine-tune, dataset train hay adapter, nên đây là model pretrained chạy inference.
- enable_thinking=True là chế độ suy luận của model, không phải huấn luyện thêm.
- Thông số sinh trong pipeline gồm temperature 0,6 và sampling; vì vậy output không hoàn toàn tất định.
- Gemini 2.5 Flash được gọi qua API để bóc tri thức offline; output được lọc/chuẩn hóa rồi import vào graph. Không có bằng chứng dùng output này để train Qwen.
- Các notebook đánh giá tạo câu hỏi nhiều mức hop và so Qwen GraphRAG với Gemini. Đây là đánh giá suy luận, không phải training loop.

## Rủi ro kỹ thuật và crawl

- Mật khẩu Neo4j xuất hiện trong repo và còn được hard-code ở pipeline. Cần xoay khóa và loại khỏi Git.
- Wikipedia/Wikidata có rate limit; bước Gemini còn phụ thuộc quota API, lỗi mạng và output JSON không ổn định.
- Câu “ĐỦ/CHƯA ĐỦ” được parse bằng substring; model trả lời dài hoặc phủ định lắt léo có thể khiến vòng lặp dừng sai.
- Cache toàn bộ tên và lấy nhiều quan hệ 1-hop có thể làm context phình lớn với node bậc cao.
- Nhiều phiên bản chatbot 2/3/4 trùng logic, dễ chạy nhầm.
- Thiếu provenance: nên trả cả QID, node/edge đã dùng và URL nguồn cùng answer.

## Đánh giá

**83/100**. Luồng nhiều vòng, đường đi graph và đánh giá thực nghiệm là điểm mạnh. Điểm trừ là không có vector RAG, không fine-tune model, pipeline offline rời rạc và còn vấn đề bảo mật/reproducibility.

## Bằng chứng code chính

- Các script gốc 1_run_discovery.py đến 9_import_enrich_data.py: ETL và enrichment.
- chatbot/4_iterative_graph_rag.py: GraphRAG lặp.
- chatbot/web_chatbot/backend/app.py: API/websocket.
- chatbot/data_eva/: bộ câu hỏi và notebook đánh giá.
- algorithm/: small-world, ranking, community detection.
