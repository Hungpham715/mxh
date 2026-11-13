# MXH — Những thứ bạn cần chuẩn bị trước khi đưa master prompt cho Claude/Codex

## Ngay bây giờ (không cần tài khoản)

- Repo `https://github.com/Hungpham715/mxh`: cho coding agent quyền đọc/ghi vào **working tree local**. Nếu dùng GitHub remote, agent có thể clone public để đọc; muốn push cần quyền GitHub riêng (master prompt mặc định cấm push).
- Máy Ubuntu có Python, trình quản lý môi trường `uv`/pip, Node.js/npm, Git. Agent phải kiểm tra phiên bản rồi mới cài; **không cần GPU** cho fake smoke và frontend.
- Dùng Profile A trong `MXH_chatbot.env.example`: chạy UI, API, fake graph, fake LLM, kiểm thử, mini synthetic dataset, tính metric synthetic.

## Khi bạn muốn truy vấn Neo4j thật

- Neo4j AuraDB: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`; trong code đã có `scope_id=nlpgraph-v1`. Ưu tiên một tài khoản **chỉ có quyền đọc** cho chatbot, nếu gói Aura cho phép; không nhầm READ routing với quyền truy cập thực.
- Agent sẽ kiểm tra số node/edge, labels, relationship types, và chọn ID thật từ DB, không cần bạn chuẩn bị tên tác giả/paper bằng tay.
- Mật khẩu AuraDB từng xuất hiện trong nội dung chat trước đây: nên **đổi mật khẩu** và chỉ đặt mật khẩu mới trong `.env` local, không paste vào prompt hoặc commit lên GitHub.

## Khi muốn chạy Qwen thật trên CPU laptop

- **Khuyến nghị:** cài Ollama local, chạy `ollama pull qwen3:0.6b`, mở service `ollama serve` khi cần. `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:0.6b`.
- Không cần `HF_TOKEN` cho Ollama local. Cần Internet một lần để download model và đủ dung lượng ổ cứng/RAM (agent kiểm tra thực tế). CPU 0.6B thường dùng được nhưng thời gian phản hồi tùy laptop.
- Nếu đang dùng Qwen SFT LoRA: chọn provider `hf_cpu`, tải base public Hugging Face nếu chưa cache, đặt `MODEL_ADAPTER_PATH` trỏ vào adapter local; **không bắt buộc upload lên Hugging Face Hub**.

## Khi tự huấn luyện SFT sau này

- Chuẩn bị môi trường GPU bên ngoài (Google Colab có thể có GPU nhưng **không được đảm bảo**). VRAM local 3GB **không được mặc định coi là đủ**; master prompt yêu cầu notebook + dry-run, chưa train thật.
- Đầu tiên chạy script tạo candidates từ Neo4j; xuất bảng CSV để người kiểm duyệt; chỉ dữ liệu **đã review** mới thành gold/test hoặc SFT training. Việc này làm qua CLI/notebook/CSV, không phải tự viết code.
- `HF_TOKEN` chỉ cần khi dùng model/dataset private hoặc khi bạn **chủ động** upload adapter, không liên quan đến việc model local có chạy được hay không.

## Không bắt buộc

- Qdrant / Chroma / FAISS / vector embedding / Elasticsearch / document parsing / PDF indexing: không dùng.
- LangSmith: không cần; nếu có bật sau cũng chỉ nên dùng khi đã được phê duyệt (vì trace có thể chứa dữ liệu/câu hỏi).
- Paid LLM API, Hugging Face paid Endpoint, W&B, cloud frontend, Redis, Postgres: không cần.

## Thứ tự chạy thực tế

1. Fake-only local smoke (UI, API, tests, dataset/eval synthetic).
2. Điền Aura env, thử read-only Neo4j queries.
3. Cài Ollama/Qwen CPU, test hỏi thật.
4. Sau này tạo/review dataset, SFT LoRA trên GPU bên ngoài.
5. Load adapter local và so B0/B1/B2 trên bộ gold test.

**Phân biệt quan trọng:** snapshot `offline/evaluation/` hiện có phục vụ kiểm tra **chất lượng node/edge của graph**, không phải benchmark chất lượng trả lời chatbot. Architecture trước đó có **kế hoạch** metric/dataset; chưa phải script/dataset chatbot đã triển khai. Master prompt yêu cầu agent viết các scripts đó.
