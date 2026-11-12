# Team 7 — Đồ thị bóng đá Việt Nam

## Kết luận nhanh

Repo làm tốt phần crawl có kiểm soát và xây knowledge graph bóng đá Việt Nam, nhưng không có GraphRAG, LLM, embedding, train model hay chatbot. Sản phẩm hiện là pipeline dữ liệu + graph analytics/shortest path, không phải hệ thống hỏi đáp AI.

- Repo: https://github.com/lh6104/VNFootballGraph/tree/main
- Commit đã đọc: ecd13eabcc445fa118671dc96cb901beecbc277b
- Nguồn đối chiếu: code, cấu hình, script test, README_USAGE.txt và Nhóm_7.pdf.

## Kiến trúc

Luồng chính nằm trong VNFootballGraphBuilder:

1. Đọc seed và cấu hình.
2. Crawl Wikipedia theo chiến lược hàng đợi/BFS.
3. Parse infobox, bảng sự nghiệp và liên kết.
4. Phân loại Player, Coach, Club, NationalTeam.
5. Chuẩn hóa thuộc tính và bóc quan hệ.
6. Dựng graph, checkpoint định kỳ và xuất JSON.
7. Script riêng chạy shortest path/phân tích.

Luồng tóm tắt: seed → hàng đợi crawl → Wikipedia page → parser/filter → entity + relation → graph → JSON/checkpoint → truy vấn.

## Node và edge

| Thành phần | Ý nghĩa | Ví dụ minh họa đúng schema |
|---|---|---|
| Player | Cầu thủ | {name: "Nguyễn Quang Hải", type: "Player", nationality: "Việt Nam"} |
| Coach | Huấn luyện viên | {name: "Park Hang-seo", type: "Coach"} |
| Club | Câu lạc bộ | {name: "Hà Nội FC", type: "Club"} |
| NationalTeam | Đội tuyển | {name: "Vietnam", type: "NationalTeam"} |
| PLAYS_FOR / PLAYED_FOR | Cầu thủ thi đấu cho đội | Player → Club |
| COACHES / COACHED | HLV dẫn dắt đội | Coach → Club/NationalTeam |
| REPRESENTS / MEMBER_OF | Cá nhân đại diện/thành viên đội | Person → Team |
| HAS_POSITION | Cầu thủ có vị trí | Player → Position |

Ví dụ trên là minh họa theo kiểu dữ liệu code, không khẳng định ba node cụ thể đều tồn tại trong output snapshot. Báo cáo còn mô tả Position và Nationality như node. Cần chốt lại schema giữa code/config và bản Neo4j cuối để tránh cùng một khái niệm lúc là thuộc tính, lúc là node.

## Pipeline và input/output

| Bước | Input | Xử lý | Output |
|---|---|---|---|
| Khởi tạo | seed kiểu list[str], URL hoặc tên trang; config giới hạn | Tạo queue, set đã thăm | trạng thái crawl |
| Tải trang | title/url kiểu str | HTTP request, rate limit, retry | HTML/wikitext kiểu str |
| Parse | nội dung trang | đọc infobox, section, bảng career | dict entity, ví dụ {name, type, nationality, career} |
| Lọc | entity/link | pattern loại trang không liên quan | entity/link hợp lệ |
| Mở rộng | các link hợp lệ | BFS/snowball | seed mới đưa vào queue |
| Bóc quan hệ | career/infobox | map cá nhân ↔ đội/vị trí | list[dict] hoặc tuple edge |
| Dựng graph | node/edge đã chuẩn hóa | thêm node và edge | graph trong bộ nhớ |
| Lưu | graph + crawl state | serialize/checkpoint | JSON/checkpoint |

Repo chú ý vận hành hơn nhiều nhóm khác: có checkpoint/resume, signal handler, giám sát bộ nhớ và giới hạn tốc độ. Đây là điểm mạnh thực tế khi crawl lâu.

## Từ user query đến answer

Không có natural-language chatbot. Luồng truy vấn thật hiện tại là script shortest path:

1. Người dùng/code cung cấp hai tên node dạng str.
2. Script đọc graph/Neo4j records.
3. NetworkX tạo node/edge.
4. Thuật toán shortest path trả danh sách node/edge trên đường nối.

Output điển hình là path kiểu list[str] hoặc text in ra console. Repo không có bước hiểu câu “Cầu thủ A liên quan CLB B thế nào?”, không có retrieval context cho LLM và không có câu trả lời văn xuôi.

Nếu bổ sung GraphRAG, luồng phù hợp là: câu hỏi → nhận diện tên cầu thủ/đội bóng → entity linking → query theo loại quan hệ và mùa giải → trả path có evidence → LLM diễn đạt.

## AI, GraphRAG và huấn luyện

| Thành phần | Trạng thái |
|---|---|
| LLM | Không có |
| Fine-tune/train | Không có |
| Embedding/vector index | Không có |
| Graph retrieval | Có ở mức truy vấn/shortest path |
| RAG answer generator | Không có |
| API chatbot | Không có |

Các bộ lọc regex/heuristic trong crawler không phải model AI. Chúng là luật do lập trình viên viết.

## Vấn đề crawl và chất lượng

- Wikipedia thay đổi cấu trúc bảng/infobox có thể làm mất trường.
- Crawl snowball có nguy cơ lan sang trang không liên quan; bộ lọc cần được đo precision/recall.
- Logic suy đoán giới tính có nhánh mặc định đối tượng không rõ thành male, gây thiên lệch dữ liệu.
- README_USAGE.txt có tuyên bố độ chính xác 100% nhưng repo không có bộ ground truth đủ để chứng minh.
- Báo cáo có chỗ nêu 983 node/2.004 edge, chỗ khác nói hơn 2.500 node; cần tách “graph đã làm sạch”, “graph thô” hoặc sửa con số.
- Quan hệ sự nghiệp nên mang thời gian, mùa giải và nguồn URL; nếu chỉ có edge Player–Club, câu trả lời lịch sử dễ thiếu ngữ cảnh.

## Đánh giá

**54/100** theo thang ưu tiên GraphRAG. Pipeline crawl có tính vận hành tốt và schema đúng bài toán, nhưng lớp AI/RAG hoàn toàn chưa có. Nếu chỉ chấm ETL graph, repo này đứng cao hơn con số 54.

## Bằng chứng code chính

- src/main.py: VNFootballGraphBuilder và luồng end-to-end.
- src/filters_advanced.py, config: lọc ngữ nghĩa, nhãn node/edge.
- scripts/test_*.py: kiểm tra bộ lọc/parser.
- shortest_path/shortest_path.py: truy vấn đường đi.
- README_USAGE.txt: hướng dẫn chạy và checkpoint.

