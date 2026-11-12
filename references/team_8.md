# Team 8 — Knowledge graph Premier League 5 mùa

## Kết luận nhanh

Repo xây dữ liệu Premier League từ Wikipedia thành CSV và Neo4j. Luồng ETL dễ nhận ra, nhưng còn lỗi schema/đường dẫn và thiếu lớp phân tích hoàn chỉnh. Không có GraphRAG, LLM, embedding, train model hay chatbot.

- Repo: https://github.com/SnowflakeTech/EPL-Wiki-Football
- Commit đã đọc: 2e4e1b384b2248d734658f8721e7056badd60b6d
- Nguồn đối chiếu: toàn bộ ETL/Cypher/data mẫu, graph.py và Group-8.pdf.

## Kiến trúc

Pipeline dự kiến:

Wikipedia trang mùa giải → danh sách mùa → CLB theo mùa → cầu thủ/HLV từng CLB → CSV node/edge → import Neo4j → query/visualize.

Các script chính chia theo đối tượng:

- crawl_seasons.py: tạo 5 mùa.
- crawl_clubs.py: lấy CLB, sân vận động.
- crawl_players.py: lấy đội hình.
- crawl_coaches.py: lấy HLV.
- build_relations.py: tạo các file quan hệ.
- import.cypher: nạp CSV vào Neo4j.
- graph.py: đọc một số quan hệ và dựng graph NetworkX.
- epl_gds.cypher: hiện trống, nên phần Graph Data Science chưa được cài đặt.

## Node và edge

| Thành phần | Ý nghĩa | Ví dụ thật trong CSV |
|---|---|---|
| Season | Một mùa EPL | {season_id: "2024-25", start_year: 2024, end_year: 2025} |
| Club | Câu lạc bộ | tên, location, stadium/capacity |
| Player | Cầu thủ | {player_id: "player_david_raya", name: "David Raya", nation: "ESP", position: "GK"} |
| Coach | HLV | tên, quốc tịch hoặc mốc làm việc |
| PLAYED_FOR | Cầu thủ thuộc CLB trong mùa | Player → Club, có season_id và position |
| COACHED | HLV dẫn CLB trong mùa | Coach → Club, có season_id, years, is_current |
| PART_OF | CLB tham gia mùa | Club → Season |

Điểm thiết kế tốt là PLAYED_FOR và COACHED giữ season_id, tránh gộp lịch sử nhiều mùa thành một quan hệ mơ hồ. Tuy nhiên Season chỉ nối trực tiếp với Club bằng PART_OF; season_id của edge khác chỉ là property, chưa phải đường graph đến Season.

## Pipeline và kiểu dữ liệu

| Bước | Input | Xử lý | Output |
|---|---|---|---|
| Crawl mùa | Danh sách 5 URL Wikipedia, mỗi URL là str | Parse tên/năm | seasons.csv |
| Crawl CLB | season_id + HTML mùa | Đọc bảng đội bóng/sân | clubs.csv và club-season mapping |
| Crawl cầu thủ | URL CLB | Đọc bảng first-team squad | players.csv |
| Crawl HLV | URL CLB/trang HLV | Parse infobox/bảng managerial | coaches.csv |
| Tạo edge | các CSV node | Ghép khóa ID và season | played_for.csv, coached.csv, part_of.csv |
| Import | file CSV | Cypher LOAD CSV/MERGE | Neo4j graph |
| Query | Neo4j records | thêm node/edge vào NetworkX | graph cho phân tích/hiển thị |

Schema edge thật:

    played_for:
    :START_ID(Player), :END_ID(Club), season_id, position, :TYPE

    coached:
    coach_id, club_id, season_id, years, is_current, COACHED

Các giá trị CSV đều là text khi đọc vào; import phải ép kiểu cho năm, boolean và số lượng nếu muốn tính toán đúng.

## Từ user query đến answer

Repo không có chatbot. graph.py hiện chạy query cố định, lấy record có player/club rồi thêm edge NetworkX. Nghĩa là input thực tế là code/Cypher do lập trình viên viết; output là graph hoặc console, không phải answer từ câu hỏi tự nhiên.

Một pipeline GraphRAG còn thiếu sẽ cần:

1. question:str, ví dụ “David Raya chơi cho CLB nào mùa 2024–25?”
2. entity extraction → {player: "David Raya", season: "2024-25"}.
3. entity linking → player_id.
4. Cypher truy xuất PLAYED_FOR có season_id tương ứng.
5. output list[dict], ví dụ [{club: "Arsenal", season: "2024-25", position: "GK"}].
6. LLM diễn đạt và kèm nguồn.

Sáu bước trên là đề xuất, không phải chức năng hiện có.

## AI, GraphRAG và huấn luyện

- LLM: không có.
- Train/fine-tune: không có.
- Embedding/vector store: không có.
- GraphRAG: không có.
- Graph analytics: file epl_gds.cypher trống, nên thuật toán Neo4j GDS chưa được triển khai trong snapshot.

## Lỗi và rủi ro đáng chú ý

- clubs.csv có hai cột cùng tên Location; cột thứ hai thực tế chứa dữ liệu kiểu sức chứa sân. Đây là lỗi schema cần sửa trước khi import.
- Code dùng cả data/node và data/nodes, dễ lỗi đường dẫn.
- graph.py hard-code password Neo4j và một vài tên cầu thủ.
- import.cypher phụ thuộc file đặt đúng vị trí nhưng repo chưa có lệnh orchestration/validation duy nhất.
- Wikipedia có bảng khác nhau theo mùa/CLB; parser cần fixture test cho nhiều cấu trúc.
- Tên cầu thủ trùng, đổi CLB hoặc đổi cách viết cần khóa bền vững hơn slug tên.
- Báo cáo nêu 1.328 node và 4.606 edge; nên có script kiểm đếm tự động sau import để tái lập.

## Đánh giá

**41/100** theo thang ưu tiên GraphRAG. Repo có bộ CSV nhiều mùa và schema quan hệ thời gian hữu ích, nhưng hiện mới dừng ở ETL graph, còn lỗi dữ liệu và thiếu AI/query layer hoàn chỉnh.

## Bằng chứng code chính

- etl/crawl_seasons.py, crawl_clubs.py, crawl_players.py, crawl_coaches.py.
- etl/build_relations.py.
- import.cypher và dữ liệu node/edge mẫu.
- graph.py.
- epl_gds.cypher.

