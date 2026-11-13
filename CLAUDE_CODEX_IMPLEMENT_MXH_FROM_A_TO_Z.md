# MASTER IMPLEMENTATION PROMPT — MXH NLP GRAPH-ONLY GRAPHRAG CHATBOT

> **Cách dùng:** dán nguyên văn nội dung file này vào Claude Code hoặc Codex đang mở **tại root của repository `Hungpham715/mxh`**. Đây là lệnh **thực thi, tạo code và kiểm thử**, KHÔNG phải yêu cầu viết thêm một bản đề xuất kiến trúc. Dùng chế độ agent có quyền đọc/ghi file, chạy shell/test; phải tôn trọng giới hạn quyền truy cập thực tế.
>
> **Ngày chốt đặc tả:** 13/11/2026. **Nguồn chỉ định:** `https://github.com/Hungpham715/mxh`, `references/team_5.md`, `references/team_6.md`, `offline/docs/schema.md`, `offline/src/graph/{derive,load}.py`, `offline/README.md`, `offline/Báo cáo nhóm 3.pdf`, và tài liệu thiết kế `NLP_GraphRAG_Qwen06_Architecture.md` nếu có tại workspace. Nếu file thiết kế không có trong repo, đặc tả dưới đây là nguồn bắt buộc, không tự giả định file đã tồn tại.

## 0. Vai trò, mục tiêu và quy tắc thực thi

Bạn là **Lead AI Engineer + Backend Engineer + Frontend Engineer + QA/MLOps Engineer**. Nhiệm vụ là **viết toàn bộ code chạy được** cho chatbot nghiên cứu mạng tác giả/tổ chức NLP từ graph Neo4j đã có, chứ không chỉ tạo tên file, TODO, skeleton, sơ đồ hay nội dung mô tả.

**Mục tiêu sản phẩm:** Một web chatbot hỏi đáp tự do bằng tiếng Việt (có thể nhận tiếng Anh) tương tác với mạng lưới học thuật NLP: tác giả, bài báo, tổ chức, chủ đề, venue và trích dẫn **trong corpus đã lưu**. UI/UX hiện đại kiểu trợ lý chat (bố cục tham khảo Claude nhưng không sao chép thương hiệu/assets), chạy local trên laptop. Backend thực hiện **Graph-only RAG**: Qwen3-0.6B hiểu câu hỏi, Python entity-link + chọn mẫu Cypher hợp lệ, Neo4j trả facts/evidence, Qwen trả lời từ bằng chứng; vòng lặp truy xuất có điều kiện tối đa **5 lần**. Người dùng **không bị giới hạn vào true/false hoặc trắc nghiệm**.

**Điều kiện cứng:**

1. `Qwen/Qwen3-0.6B` là model thật mục tiêu; **inference trên CPU localhost**. Chạy được toàn bộ sản phẩm ngay bằng **deterministic fake LLM + fake graph** khi chưa có model, GPU hoặc tài khoản DB. Chế độ fake có nhãn rõ, không được ngụy tạo kết quả thực nghiệm thật.
2. Dùng **Neo4j AuraDB hiện có** khi có credentials; tri thức chỉ từ **nodes, relationships, properties trong graph**. **CẤM** Qdrant, Chroma, FAISS, Milvus, vector embeddings/index, Neo4j full-text index/search, BM25, `db.index.fulltext.*`, PDF parsing, document chunking/retrieval, LangSmith bắt buộc, web search lúc trả lời, multi-agent, LangGraph Subgraph, native autonomous tool-calling. Không lấy `Paper.abstract` làm kho retrieval văn bản; nếu hiển thị nó như thuộc tính của paper đã được tìm bằng graph thì phải phân biệt rõ, và không tạo full-text search trên abstract.
3. **Không để model sinh Cypher tự do rồi chạy.** Qwen chỉ xuất các action/intent/arguments JSON theo whitelist; Python mapping vào **parameterized Cypher templates**, enforce read-only, scope, hard limits.
4. `MAX_ITERATIONS=5` nghĩa là tối đa **5 lượt truy xuất suy luận (reasoning retrieval steps) cho một câu hỏi**, không phải 5 cạnh graph; thao tác tải cache tên ban đầu/entity linking/healthcheck là truy vấn hạ tầng tách biệt, phải log riêng và không bị giả vờ tính vào 5 lượt. Một câu Cypher 3-hop vẫn tính **1 iteration**. Dừng sớm khi đủ bằng chứng, thiếu dữ liệu, không có tiến triển, lặp action/params, timeout, hoặc entity mơ hồ.
5. **Giữ nguyên pipeline `offline/`** (8 JSONL, manifest, loader, schema, analysis, test, số liệu) và không xóa/mutate graph. Có thể đọc và reuse; các thay đổi cần thiết nhỏ ngoài `chatbot/` phải giải thích và không phá test cũ. Scope Neo4j `nlpgraph-v1`. Tuyệt đối không `DETACH DELETE`, `DROP`, `CREATE/MERGE/SET` trong chatbot live, không đổi schema ngoài phạm vi mà chưa xin phép.
6. **Không bịa ra file/data/model/credentials**, không tuyên bố đã train, đã chạy live Neo4j hay đạt accuracy khi chưa làm. Nếu network, Aura credentials, model weights hoặc GPU không có, **thực hiện toàn bộ phần khác + fake integration + unit/integration tests**, ghi blocker bằng lệnh khôi phục cụ thể, tiếp tục làm, KHÔNG dừng cả task.
7. Tôn trọng root `CLAUDE.md`, đặc biệt skill `.claude/skills/coding-simple/SKILL.md` và các quy tắc frontend nếu sẵn có; kiểm tra trước khi viết code. Ưu tiên code rõ ràng, interfaces đơn giản, tránh phức tạp hóa.
8. Không tự push repo, đưa secrets lên GitHub, gửi telemetry ra ngoài hoặc upload weights/dataset lên Hugging Face nếu chưa được phê duyệt. Không tự chạy script lạ từ repo năm ngoái. Không hardcode password, token, model credentials. Trong repo clone về có thể có thông tin nhạy cảm: không copy/commit chúng.
9. **Chịu trách nhiệm sửa đến khi toàn bộ acceptance tests khả thi trong môi trường hiện tại đều pass**. Chạy lặp `implement → test → inspect errors → fix → retest`. Không dừng ở “đã tạo file”; không tô xanh test bằng skip vô lý. Ghi chính xác test nào chưa thể chạy do thiếu dependency/external resource.
10. Khi gặp mâu thuẫn giữa tài liệu tham khảo và source code thực tế, **source code + schema hiện tại thắng**. `team_5.md` là reference, không phải task mới bắt copy y nguyên; `offline` là dữ liệu thật. Không đưa pipeline giới hạn MCQ/TF từ nhóm 9 vào chatbot.

**Chiến lược làm việc:** trước tiên `git status`/audit, sau đó code + test theo từng khối, sau cùng chạy smoke E2E fake + optional live. Chỉ hỏi chủ repo khi thực sự **không thể quyết định an toàn** (ví dụ quyền xóa DB, nguồn secrets, thay đổi business scope); những lựa chọn implementation nhỏ hãy chọn cách đơn giản nhất và ghi vào ADR/README, đừng lặp câu hỏi không cần thiết.

---

## 1. Inspect/audit repository và bài năm ngoái trước khi code

### 1.1 Audit repo hiện tại

- Xác định root, branch, Git status, Python/Node/Ollama/VRAM/RAM, port rảnh, OS. Không assume repo blank. Không overwrite thay đổi chưa commit của chủ repo.
- Đọc `CLAUDE.md`, `.claude/skills/coding-simple/SKILL.md` nếu có, `offline/README.md`, `offline/docs/schema.md`, `offline/src/graph/{derive,load}.py`, `offline/src/common.py`, `offline/configs/topics.yaml`, `offline/output/neo4j/import_report_latest.json`, `references/team_5.md`, `references/team_6.md`.
- Kiểm tra `chatbot/` đã có chưa. Nếu có, **tích hợp và sửa**, không tạo song song `chatbot2`, `new_chatbot`, v.v. Dùng `git diff` trước khi đổi file.
- Kiểm tra tệp nguồn data thực/ví dụ fixtures. `offline/data/fixtures/*.jsonl` là **synthetic fixture**; không được gọi là graph sản phẩm thật.
- In/nghi lại schema từ code thật, không đoán field.

### 1.2 Tự clone và nghiên cứu các nhóm năm 2025

- `references/team_*.md` đã tồn tại: **KHÔNG thay thế/xóa**. Đọc **tất cả** các repo URL được nêu rõ trong `references/*.md`, kiểm tra tính tồn tại. `git clone --depth 1` mọi repo public truy cập được vào `references/external/team_04/`, `team_05/`, `team_06/`, `team_07/`, `team_08/`, `team_09/`, `team_13/`... tương ứng (đừng tự bịa URL cho nhóm không có). Ưu tiên đọc sâu team 5/6/9; các nhóm còn lại audit ngắn. Kiểm tra dung lượng/disk/network; nếu repo quá lớn, dùng shallow/sparse checkout phù hợp hoặc ghi rõ đã bỏ qua có lý do, **không để cloning làm block sản phẩm**.
- Ghi `.gitignore` cho `references/external/` (không vô tình commit nested `.git`, checkpoints, credentials, hàng GB weights). Ghi `references/REPOSITORY_AUDIT.md` với URL, branch, commit SHA, tệp thực đã đọc và chức năng rút ra.
- **Không chạy code của các repo tham khảo**, không copy nguyên code khi chưa xác định license; sử dụng để kiểm chứng workflow và viết code riêng.
- Phân biệt cụ thể: nhóm 5 `NER/entity-link → regex intent → Cypher → Qwen paraphrase`; nhóm 6 `Qwen entity → graph query → đủ/chưa đủ → mở rộng tối đa 5 vòng`; nhóm 9 có LangGraph nhưng luồng cuối chỉ TF/MCQ. Không gọi nhóm nào “multi-agent” nếu không có bằng chứng.
- Nếu clone fail: dùng file `references/team_*.md` đã có, đọc GitHub với kết nối hiện tại, log lỗi clone nhưng **không block** implementation.

### 1.3 Đọc tài liệu architecture

- Nếu có `NLP_GraphRAG_Qwen06_Architecture.md`, đọc kỹ và kiểm những pseudocode có thể chưa đúng (ví dụ delta facts phải tính **trước** merge). Nếu chưa có, tạo `chatbot/architecture.md` dựa vào spec này, không chỉ là bản copy PRD.
- Ghi `chatbot/docs/DECISIONS.md`: lựa chọn, tradeoff, nguồn bằng chứng; ghi `chatbot/docs/LIMITATIONS.md`: các giới hạn corpus và pipeline thực tế.

---

## 2. Schema Neo4j thật — bắt buộc tương thích

**Hiện có trong `offline/`:**

- Labels: `Author(id,name,orcid,openalex_id,acl_author_id,identity_status)`, `Paper(id,title,year,abstract,doi,acl_id,arxiv_id,source_kind,source_url,venue_id,openalex_id,abstract_origin)`, `Institution(id,name,ror,country_code,source_url)`, `Venue(id,name,kind,year,source_url)`, `Topic(id,topic_key,name,description,rule_version)`.
- 10 relationships whitelist: `FIRST_AUTHOR_OF` Author→Paper, `OTHER_AUTHOR_OF` Author→Paper, `COAUTHORED_WITH` Author—Author, `AFFILIATED_WITH` Author→Institution, `APPEARS_IN` Paper→Venue, `HAS_TOPIC` Paper→Topic, `CITES` Paper→Paper, `ORG_COAUTHORED_WITH` Institution—Institution, `RESEARCHES` Author→Topic, `ACTIVE_IN` Institution→Topic.
- Quan hệ được định nghĩa **có hướng trong DB**, nhưng các cặp **đối xứng** `COAUTHORED_WITH` / `ORG_COAUTHORED_WITH` chỉ lưu một cạnh theo ID. Khi query quan hệ đối xứng dùng `-[r:REL]-`, không chỉ `->`.
- Thuộc tính cạnh có thể gồm `scope_id`, `source_url`, `evidence_paper_ids` (list ID bài báo), `evidence_count`, `shared_count`, `first_year`, `last_year`, `years`, `position`, `author_position`, `rule_id`, `evidence_span`, `confidence_band`.
- Scope mặc định `nlpgraph-v1` ở **node và relationship**; mọi truy vấn live phải lọc scope đúng, kể cả node trung gian, edge và source paper.
- Snapshot report (chưa phải truy vấn live ở phiên này): 7,134 nodes, 30,971 edges; 1,091 Paper, 5,430 Author, 600 Institution, 7 Venue, 6 Topic; 26 CITES, 451 HAS_TOPIC. Chỉ tham khảo và đối chiếu live, đừng hardcode số làm kết quả chatbot.
- `AFFILIATED_WITH` nghĩa là tổ chức được ghi trên một/các **paper cụ thể**, không phải nơi làm việc hiện tại. Khi trả lời tổ chức trong bài hợp tác, tính **intersection** `co.evidence_paper_ids ∩ af.evidence_paper_ids` và trả Paper.source_url.
- `CITES` là internal-corpus citations; không nói “toàn bộ citation” hay đo ảnh hưởng toàn cầu. `RESEARCHES` và `ACTIVE_IN` là quan hệ suy diễn theo ít nhất 2 bài trong corpus. Paper không có `HAS_TOPIC` không có nghĩa nó không thuộc lĩnh vực đó. Không bao giờ bịa chủ đề do thiếu nhãn.
- Neo4j user cho chatbot nên có **quyền chỉ đọc thật** nếu dịch vụ cho phép; `READ_ACCESS`/routing read không phải security boundary. Chỉ chạy catalog Cypher được code review và tham số hóa.

**Bất biến phải được kiểm thử:** bằng chứng của facts có paper_id tồn tại và `scope_id` đúng; hướng và pair đối xứng đúng; query không cross-scope; không có write queries; không thổi phồng nguồn.

---

## 3. Sản phẩm & kiến trúc bắt buộc

### 3.1 Kiến trúc online

```
React UI (chat + sidebar + evidence + debug) --POST /api/chat--> FastAPI
    → QueryParser (Qwen CPU / FakeLLM)
    → EntityLinker (exact ID/name + RapidFuzz, NO full-text index)
    → Planner (intent → QueryStep whitelist)
    → CypherTemplateRegistry → GraphRepository (Neo4j read only / FakeGraph)
    → EvidenceCollector/Normalizer (fact IDs, proof Paper IDs, URLs)
    → SufficiencyChecker (hard rules + optional Qwen next-step proposal)
    → iterative coordinator (max 5 DB query steps; dedup; no-progress; timeout)
    → GroundedAnswerGenerator (Qwen CPU / FakeLLM)
    → GroundingValidator + source citations
    → JSON / optional SSE progress → UI
```

**Không LangGraph bắt buộc**. Dùng Python state machine rõ ràng để tránh setup thừa; KHÔNG tạo Agent, native Tool Calling, đa subgraph chỉ để có tên công nghệ. Nếu triển khai LangGraph phải có lý do đo được và giữ nguyên `max_iterations=5`, nhưng mặc định **không dùng**.

### 3.2 Model-provider interface bắt buộc (khả năng thay thế)

Viết adapter theo protocol/interface thống nhất, ví dụ `LLMProvider.generate(messages, *, temperature, max_tokens, json_mode) -> LLMResponse` (có thể tách parse/decision/answer wrappers); có **đúng ba backend**:

- `fake`: deterministic, **không tải model**, không network, phục vụ E2E và kiểm thử. Response được lập trình deterministic đủ để demo 6–10 intents trên **synthetic graph**, có nhãn `SIMULATED — no real LLM/DB` trên giao diện. Test phải xác minh việc gắn nhãn.
- `ollama`: gọi **Ollama local** `http://127.0.0.1:11434/api/chat`, model `qwen3:0.6b`, `stream=false` cho parse/decision, `think=false` nếu model hỗ trợ; tự probe readiness `/api/tags`, timeout, fallback lỗi rõ ràng, không tự giả kết quả. **Đây là live CPU baseline mặc định khi user bật mode real**. Dùng API thực được xác minh, không gửi request tới cloud.
- `hf_cpu`: dùng `transformers` + `peft` đọc `Qwen/Qwen3-0.6B` và **optional local LoRA adapter** từ `MODEL_ADAPTER_PATH`, `device="cpu"`, không yêu cầu model upload lên Hub. Lazy-load **một lần**, không load trong mỗi request; non-thinking cho JSON output; tách output khỏi prompt tokens và xử lý đúng `apply_chat_template`/EOS. CPU có thể chậm: timeout/configurable; không chạy model thật trong smoke tests mặc định.

**Cấm silently fallback từ Ollama lỗi về FakeLLM trong mode real.** Chỉ chuyển khi người dùng chủ động chọn `MODE=fake`; nếu real không chạy được, `/health` báo degraded, UI hướng dẫn `ollama pull qwen3:0.6b` và trả lỗi rõ.

### 3.3 API contracts cần code thật

- `GET /api/health`: backend + selected provider + graph provider + model status; không lộ secrets. `GET /api/config/public`: tên mode, scope, limits (không key).
- `POST /api/chat`: `{question, session_id?, history?, debug?}` → `{answer, status, complete, iterations_used, stop_reason, sources:[{paper_id,title,url,claim_ids?}], facts_count, trace?, provider_info?}`.
- `POST /api/chat/stream` (ưu tiên nếu thời gian): **SSE qua POST fetch streaming**; events `start`, `parse`, `linked`, `query_start`, `query_result`, `decision`, `answer`, `done`, `error`. Frontend dùng `fetch()+ReadableStream`, KHÔNG dùng browser `EventSource` POST; không gửi raw model thoughts. Tất cả vẫn có `POST /api/chat` non-stream fallback.
- `GET /api/graph/preview` optional: số label/relation/types/top-n chỉ khi có graph; fake có watermark; không leak PII/secrets.
- CORS chỉ cho URL frontend từ env; không `*` khi credentials. Request limits, structured error, id/timestamp, controlled timeout. Schema bằng Pydantic.
- Session history: localStorage của UI hoặc dữ liệu history client gửi về có giới hạn, KHÔNG giả persistent server memory. Chat follow-ups chỉ được coi là supported nếu code resolve được referent; nếu không trả hỏi làm rõ. Đặt TTL/paging khi lưu history.

### 3.4 Python data contracts + tests

Tạo những model thực sự sử dụng được, có field/validator/type annotations:

- `QueryIntent(intent, entities:[{text,type}], filters:{year_from,year_to,topic_id}, requested_fields, unsupported)`.
- `LinkedEntity(label,id,name,score,identity_status, ambiguous_candidates)`.
- `QueryStep(action, params, expected_fields, limit, fingerprint)`.
- `GraphFact(fact_id,subject_id,predicate,object_id?,value?,paper_ids,source_url?,year?,claim_type,limitations)`.
- `QueryState(question, linked_entities, planned_steps, executed, seen_fingerprints, facts, goals_remaining, iteration, max_iterations, stop_reason, status, sources, answer)`.
- `NextDecision(sufficient, missing_goals, next_action?, params?, reason_code)`.
- `ChatResponse` và `Citation` phù hợp API.

Pydantic validation strict: unsupported intent/label/action → error/fallback, không lấy `cypher` sinh từ model; câu JSON không hợp lệ chỉ retry **một lần**, sau đó dùng parser regex/rules đã kiểm thử (nếu có match chắc chắn, kèm `parse_source=rules_fallback`) hoặc trả lỗi an toàn. Không tự chuyển sang FakeLLM trong mode real. Fake phải trả đúng contracts; mọi adapter kiểm cùng bộ contract tests.

---

## 4. Câu hỏi mở: catalog truy vấn PHẢI code và test

Ít nhất 12 intent thật, có `templates.py`/registry với tham số không nội suy chuỗi user:

1. `author_papers`: danh sách bài của tác giả + paper/year/URL, quan hệ FIRST/OTHER.
2. `coauthors`: đồng tác giả + shared_count + paper IDs bằng chứng.
3. `shared_papers`: bài chung của A/B, query đối xứng, trả Paper URLs.
4. `author_affiliations`: tổ chức **theo bài**, năm và chứng cứ.
5. `coauthor_affiliations`: giao paper IDs giữa coauthor & affiliation, không đoán affiliation hiện tại.
6. `paper_authors`: tác giả đứng đầu và những tác giả khác, theo `position`.
7. `topic_papers`: các bài **đã gắn nhãn** `Topic`, lọc năm nếu có.
8. `paper_venue`: bài đăng tại Venue nào.
9. `paper_citations`: hai chiều có hướng (papers cited by X; papers citing X) **trong corpus**.
10. `org_collaborations`: tổ chức xuất hiện chung trên bài, paper IDs.
11. `author_path`: đường **coauthor-only**, tối đa 4 cạnh trong Cypher, có paper evidence cho từng edge; không đi tắt qua Venue/Topic.
12. `network_top`: ranking đồng tác giả trong corpus (theo số người và/hoặc `shared_count` với tên metric rõ).

Có thể bổ sung intent `author_topics`, `institution_topics`, `paper_topic`, `unknown` nếu đủ bandwidth nhưng không làm giảm chất lượng 12 intents nêu trên. **Tất cả** phải có route → QueryStep → Cypher → data normalization → answer → tests. Không chỉ khai báo tên trong enum.

**Đầu tiên code/query được các cases quan trọng mà không cần LLM**, dùng direct intent fixture để test correctness. Sau đó mới gắn Qwen.

**Entity linking:**

- Không Neo4j full-text index; chỉ exact ID, exact normalized `name`, fuzzy RapidFuzz trên danh sách `{id,label,name}` được lấy từ Neo4j và cache khi cần, chỉ ~7k nodes nên đủ nhỏ; có timeout và refresh thủ công/TTL.
- `Author.name` có thể trùng: trả 2–3 candidates và yêu cầu người dùng chọn bằng ID, **không tự đoán**. Cho phép search theo id như `oa:A...` và case-insensitive title; tối ưu bằng index property thường nếu đã có, không tự tạo DDL ở live chatbot.
- Mốc fuzzy khởi đầu score ≥90, margin ≥8 chỉ là config có test, không báo accuracy khi chưa đo. Exact name có nhiều IDs vẫn ambiguous.

**Cypher read-only:**

- Whitelist constants do developer viết. Dùng `$scope`, `$author_id`, `$paper_id`, `$limit`, `$year`, `$topic_id`; validate IDs từ entity linker, hard cap limit/timeout.
- Check tất cả node/cạnh intermediate cùng scope, không chỉ anchor. Truy vấn `-[:COAUTHORED_WITH]-` do DB chỉ lưu 1 chiều ID.
- Dẫn chứng lấy từ `Paper.source_url` của **paper IDs có thật**. Nếu chưa có chứng cứ, fact không được biến thành citation giả.
- `READ_ACCESS`/read routing + **server credentials read-only** nếu có. Ghi rõ read routing **không tự bảo đảm** chống ghi; kiểm soát bằng whitelist và quyền DB.
- Query explain/profile chỉ optional thủ công; không chạy query nặng nếu không có Aura. Unit tests kiểm no-write syntactically và contract; integration với live DB (nếu có) kiểm 12 templates với record ID thật.

---

## 5. Iterative GraphRAG — max 5 query iterations

Cơ chế thật giống nhóm 6 về vòng lặp, nhưng cải thiện bằng schema JSON/hard-stop:

1. Qwen parse question thành `QueryIntent`; Python entity-link và planner xác định mục tiêu thông tin.
2. Chọn bước hợp lệ trong catalog, nếu câu hỏi 2–4-hop giải quyết trong một Cypher thì chỉ **1 iteration**.
3. Thực hiện Neo4j query (tối đa 20 records/step mặc định; nếu cắt danh sách, trả cờ `truncated=true` và thông báo đây chỉ là các kết quả đầu), convert thành `GraphFact` đã kiểm chứng; merge theo `fact_id` chứ không append trùng.
4. Python xác định `new_facts_delta` **trước khi merge**, tính `goals_remaining` bằng quy tắc gắn với intent; tránh Qwen tự tuyên bố đủ khi thiếu field bắt buộc.
5. Nếu đủ, **STOP**. Nếu chưa đủ và còn ngân sách, Qwen có thể đề xuất `NextDecision` gồm `action` (whitelist) và các **IDs đã xuất hiện trong facts hoặc ban đầu**; Python validate/plan. Nếu Qwen không sinh được step hợp lệ, có deterministic fallback có căn cứ hoặc stop `no_progress`, không loop mãi.
6. Chặn lặp `(action, canonical_json_params)` bằng fingerprints. Dừng nếu không có facts mới, tất cả candidate entity đã thử, thời gian hết, query trả empty, ambiguous chưa được giải quyết, hoặc 5 iterations.
7. Ở `max_iterations`/`partial`, trả điều đã có chứng cứ và nêu không đầy đủ; **không cố invent fact** để có câu trả lời.

Bắt buộc có unit test:

- 1-hop kết thúc 1 lượt; multi-hop iterative 2–3 lượt; path 3-hop nhưng **1 query**;
- `MAX_ITERATIONS=5` không bao giờ vượt, kể cả LLM liên tục nói `CHƯA ĐỦ`;
- no-progress stop; duplicate-step stop; malformed JSON; missing node; ambiguous name; out-of-scope; DB timeout; invalid source URL; info về affiliation trong paper khác **không được ghép sai**;
- streaming và non-stream trả cùng answer/sources/status khi fake deterministic.

**Important:** `iteration` = một lần thực thi query step. Không đếm vòng parse/answer LLM thành iteration; log riêng số `llm_calls`.

---

## 6. Grounded answers, citations và sự an toàn của dữ liệu

- Prompt Qwen answer chỉ nhận `question + verified graph facts + constraints`, tuyệt đối không thêm dữ liệu ngoài graph. Model phải phân biệt `answered`, `partial`, `not_found`, `ambiguous`, `out_of_scope`, `error`.
- Tạo nguồn trích dẫn từ `Paper.id/title/source_url`, **server-side** từ Neo4j và evidence mapping, không cho LLM bịa URL/ID. UI hiện Paper title/clickable source; mở trang ngoài khi người dùng click.
- Số đếm/ranking/năm lấy **trực tiếp từ query result**, không để LLM tự cộng khi có số chuẩn.
- Chặn instruction injection trong `name/title/abstract` (data string != system instruction); sanitize UI Markdown, chống XSS.
- Phải trả rõ rằng câu trả lời chỉ theo corpus 2023–2025 được lấy mẫu. Chỉ 26 CITES, phần lớn Paper thiếu Topic; không suy diễn “paper không thuộc Topic” hay “tác giả hiện tại làm ở Institution X”.
- Nếu UI có chế độ DEBUG, hiện các query action, số records, evidence, iteration và stop reason; **không hiện internal chain-of-thought của model**, credentials hoặc raw sensitive logs.

---

## 7. UI/UX hoàn chỉnh như ứng dụng chat hiện đại

**Không dùng Gradio làm UI chính**. Tạo frontend mới bằng **React + TypeScript + Vite**, Tailwind CSS (hoặc CSS Modules nếu setup/version phức tạp), responsive. Thiết kế **lấy cảm hứng bố cục chatbot Claude** nhưng không sao chép logo, assets, tên thương mại, hoặc pixel-perfect proprietary UI.

**Bắt buộc code thật, không chỉ HTML screenshot/mock:**

- Sidebar thu gọn/mở được: `New chat`, danh sách hội thoại localStorage, đặt lại tên/xóa hội thoại; badge mode fake/real.
- Layout tối giản, sáng/tối, typography đọc tốt, khung nhập rộng và placeholder hướng dẫn (ví dụ câu hỏi về tác giả/bài báo NLP), nút gửi/stop, Enter gửi / Shift+Enter xuống dòng; hỗ trợ mobile.
- Chat bubbles cho user/assistant, render Markdown có sanitize, code blocks có copy, trạng thái loading/typing, empty state có suggested questions lấy từ **fixture hoặc live IDs đã xác minh**, tuyệt đối không bịa tên học giả trong demo nếu không tìm được.
- Với assistant answer: nguồn bài báo có title/URL, expandable “Evidence”, “Graph query steps (1–5)” và step timeline. Hiển thị rõ `partial/not_found/ambiguous`; khi ambiguous có candidate cards để user chọn ID và hỏi lại.
- Các tình trạng lỗi: Ollama chưa chạy, Neo4j chưa cấu hình, mất kết nối, timeout, API error, input dài, không có data; không hiển thị blank trắng.
- Chỉ gọi backend qua HTTP, không fake dữ liệu trong frontend khi mode real. Kết nối `POST /api/chat`, nếu stream có thì streaming parser chính xác, cancel qua `AbortController`.
- Accessibility: keyboard focus, labels, aria, contrast, reduced-motion; UI usable 360px phone → desktop.
- Screenshots/playwright smoke nếu browser khả dụng. Nếu không có browser engine, test React component and build, ghi limitation.
- Không tải remote tracking/analytics fonts/assets bắt buộc; frontend chạy hoàn toàn localhost.

---

## 8. Train Qwen3-0.6B — CHỈ SET UP, không bắt buộc train thật

**Quyết định phương pháp:** SFT + LoRA, không DPO/GRPO trong v1. Train để model học **PARSE / NEXT_STEP / ANSWER** theo schema, **không học thuộc toàn bộ graph**. Phải giữ baseline model gốc để so sánh, không tuyên bố SFT tốt hơn khi chưa eval.

**Laptop người dùng có 3 GB VRAM; inference chắc chắn chạy CPU.** Không tự chạy `pip install torch-cuda` khổng lồ hoặc full training trên laptop. GPU 3GB không được bảo đảm đủ ổn định cho SFT vì còn phụ thuộc GPU/sequence/config; **không cam kết chạy QLoRA trên 3GB**. Local dev chỉ chạy lint/unit/validation/smoke với fake/tiny dataset. Nếu cần train thật, thiết kế **Notebook Colab GPU** (GPU Colab không được đảm bảo) và CLI tùy chọn GPU khác.

Phải **tạo và test** (notebook tự chứa code các cell, không phải markdown khung):

- `chatbot/training/notebooks/qwen3_06b_sft_colab.ipynb` gồm: môi trường/cài dependencies version-compatible → mount/download dataset (không để key trong notebook) → validate JSONL → seed/dedup/train-val split → test tokenizer/chat_template (Qwen3 enable_thinking=False khi JSON) → check CUDA/VRAM → load base → PEFT LoRA → TRL SFTTrainer → dry-run `max_steps=1` **chỉ khi GPU & approved data tồn tại** → eval → save adapter **local** → export to user destination + inference smoke. Không tự upload ra HF. Nếu chạy notebook locally thiếu CUDA, chỉ run cell kiểm schema, tokenize miniature synthetic data nếu model cached, và đưa thông báo skip training rõ ràng.
- `chatbot/training/train_sft.py` CLI/entrypoint dùng chung core training code với notebook (không duplicate hai engine khác nhau); hỗ trợ `--dry-run` (schema, split, tokenize optional, VRAM probe, config without optimizer), `--train` gated GPU+dataset+explicit flag; resume checkpoint.
- `chatbot/training/config_sft.yaml` params **khởi điểm phải tune**: LoRA r=8/16, alpha=16/32, dropout=0.05, learning_rate≈1e-4, max_length=512 hoặc 1024 PARSE (2048 ANSWER nếu GPU đủ), batch_size=1, grad accumulation 8–16, 2–3 epochs, seed=42, eval strategy. Dùng completion-only/assistant-only loss đúng theo TRL version và Qwen chat template; không tự assume hai mode y hệt.
- `chatbot/training/export_adapter.py` (local save path) và `chatbot/training/smoke_adapter.py`: xác minh có adapter_config.json + adapter weights, thử load Qwen base+PEFT **CPU** nếu đủ RAM/model sẵn; nếu thiếu model thì chỉ validate metadata và báo skipped. Có lệnh chuyển mode `hf_cpu` trong README.
- `chatbot/training/HF_OPTIONAL_UPLOAD.md`: nếu tương lai muốn upload, ghi quy trình opt-in dùng `HF_TOKEN` + private repo, **không mặc định làm**. Không hardcode HF handle.

**Tuyệt đối không yêu cầu Hugging Face Hub để inference sau SFT**: checkpoint local (adapter folder) + base model cached/download được là đủ. Ollama `qwen3:0.6b` là baseline CPU; **nó KHÔNG tự nạp adapter PEFT**. Khi có adapter mới, chuyển qua provider `hf_cpu` hoặc thực hiện quy trình merge/quantize Ollama riêng được kiểm chứng, không pretend Ollama đã dùng SFT.

---

## 9. Dataset generation + human review + evaluation (BẮT BUỘC CÓ CODE)

**Chưa cần tạo bộ gold thật lớn hay train/eval thật lúc này**; nhưng phải có scripts/notebook/schemas/methods chạy được để **sau này người dùng chỉ chạy lệnh và kiểm nhãn, không phải lập trình lại**. Không biến “khó” thành excuse bỏ qua code.

### 9.1 Tạo dataset có công cụ thật

Tạo ít nhất:

- `chatbot/datasets/schema.py`: schema cho `QuestionCase`, `ExpectedQuery`, `ExpectedFacts`, `ExpectedCitations`, `SFTSample`, `ReviewStatus`. JSON Schema docs và examples.
- `chatbot/datasets/generate_from_graph.py`: CLI **read-only Neo4j** + các query templates → sample tác giả/bài báo/quan hệ/path **đã tồn tại** → generate natural-language questions từ template tiếng Việt/Anh → expected entity IDs, intent, paper IDs và answers **deterministic**, các provenance fields `scope_id`, `snapshot_version`, `template_id`, `group_id`, `seed`; limits/rate and no API spend. Với `--provider fake` sinh từ synthetic graph, end-to-end chạy mà không Aura.
- `chatbot/datasets/generate_negative.py`: sample `not_found`, `out_of_scope`, ambiguous-name, missing affiliation, no citation, no topic, cross-scope; đảm bảo negative **được kiểm chứng** chứ không tùy tiện giả định không có relation từ một corpus mẫu.
- `chatbot/datasets/split.py`: reproducible group split **trước** paraphrase, ngăn paraphrase và cùng paper/author ID leak train/val/test; nếu split quá hạn chế ghi tradeoff, test leakage checker.
- `chatbot/datasets/augment_questions.py`: CLI optional dùng local Qwen hoặc external explicitly-configured LLM để paraphrase, phải validate giữ nguyên label/entity/relation; mặc định rule-based và không cần API key. Dữ liệu augment chưa kiểm phải `needs_review`, không tự coi là gold.
- `chatbot/datasets/export_review.py`, `import_review.py`: xuất CSV dễ mở bằng Excel/Google Sheets với `question,expected_answer,expected_entities,expected_paper_ids,source_urls,label_valid,reviewer_note`; human sửa/đánh dấu rồi import; validate schema, reject invalid rows, log rejected. Không yêu cầu con người viết code. `label_valid=unknown` chưa gold.
- `chatbot/datasets/build_sft.py`: chuyển **reviewed samples only** thành `{prompt,completion}` cho `TASK=PARSE`, `TASK=NEXT_STEP`, `TASK=ANSWER`, đảm bảo `assistant_only/completion_only` đúng; không leakage, không dùng test làm train, refuse nếu không đủ data, output manifest/checksum.
- `chatbot/datasets/notebooks/prepare_and_review_dataset.ipynb` tùy chọn, hướng dẫn từng cell; bắt buộc CLI scripts cũng làm được, notebook không phải con đường duy nhất.

**Phân biệt datasets:** `data/synthetic/` test fixtures; `data/generated/` candidates; `data/reviewed/` reviewed only; `data/splits/` train/val/test; `data/models/` adapters (gitignored). `README_DATASETS.md` nêu khác biệt. Code chạy tạo **mini synthetic sample 10–30 câu** để test plumbing, nhưng không tự tuyên bố có benchmark/gold thật.

### 9.2 Evaluation code thực thi được

- `chatbot/evaluation/run_eval.py` CLI: nhận `--provider fake|ollama|hf_cpu`, `--graph fake|neo4j`, `--dataset ...`, `--max-iterations 1|5`, `--output-dir`, `--seed`; gọi **chính chatbot pipeline** thay vì logic đo khác. Nếu không có reviewed gold, fail with actionable error hoặc chạy `--synthetic-smoke` riêng (không tự báo benchmark chính thức).
- `chatbot/evaluation/metrics.py`: JSON validity, intent accuracy, entity extraction precision/recall/F1, entity-link Top-1, query-template accuracy, query execution success, evidence recall/precision when reviewed gold exists, answer exact-match/token F1 for extractive facts, numeric exactness, citation ID/URL precision, source-supported rate when claim labels available, refusal accuracy, multi-hop success, premature-stop rate, iterations avg/p95, latency median/p95, timeout/error counts. **Không tự tạo metric factual correctness hay hallucination rate từ LLM judge chưa được label**, ghi `not_measured` khi thiếu nhãn.
- `chatbot/evaluation/compare.py`: B0 = Qwen base + one-step, B1 = Qwen base + iterative ≤5, B2 = Qwen + SFT adapter + iterative ≤5; chỉ so trên **cùng held-out reviewed test**. Không có SFT thì B2 = `not_run`, không fake.
- Xuất `reports/eval/summary.json`, `.csv`, `.md`, per-case predictions/traces, config/model hash, graph snapshot/version, run timestamp; khi fake gắn `synthetic_smoke_only=true` và banner.
- `chatbot/evaluation/README.md`: hướng dẫn cho chủ repo theo 5 bước chỉ **run commands → review labels → run train sau → run eval → mở báo cáo**.

### 9.3 Test fixtures & minimum demos

- Tạo synthetic mini graph gồm ít nhất 4 Author, 4 Paper, 2 Institution, 2 Venue, 2 Topic; edge Evidence consistent; một cặp hợp tác, một trường hợp affiliation ở paper khác để kiểm không nhầm, một người trùng tên/ID khác, một topic missing.
- `pytest` cover dataset generation/splitting/leakage, reviewer IO, metric formulas, comparison absent-B2, bounded loop, evidence and source correctness.
- **Không chạy dataset generation quy mô lớn trên Aura hoặc dùng API trả phí khi chưa có `--execute`/explicit config**. Tests mặc định local fake.

---

## 10. File structure — PHẢI TẠO CODE THẬT (được điều chỉnh nhỏ nếu có lý do)

```
mxh/
  CLAUDE.md                         # keep existing; append chatbot notes only if helpful
  offline/                          # KEEP EXISTING CODE + DATA intact
  references/
    team_5.md, team_6.md, ...       # KEEP, do not overwrite
    external/                       # shallow clones; gitignored
    REPOSITORY_AUDIT.md
  chatbot/
    README.md
    architecture.md
    .env.example
    pyproject.toml                   # OR root workspace optional; don't break offline
    config.yaml
    src/graphrag/
      __init__.py
      settings.py                    # env/config, validation
      models.py                      # QueryIntent/QueryStep/Fact/State/Response
      llm/base.py
      llm/fake.py
      llm/ollama_cpu.py
      llm/hf_cpu.py
      llm/prompts.py
      entity_linking.py
      intent_parser.py
      planner.py
      cypher_templates.py
      graph/base.py
      graph/neo4j_readonly.py
      graph/fake_graph.py
      evidence.py
      sufficiency.py
      answer.py
      workflow.py
      api.py
    data/synthetic/               # tiny fixtures only
    datasets/                     # implemented generator, augment, review, split, SFT exporters
    evaluation/                   # implemented metrics + evaluation runner + comparison
    training/
      notebooks/qwen3_06b_sft_colab.ipynb
      config_sft.yaml
      train_sft.py
      export_adapter.py
      smoke_adapter.py
      HF_OPTIONAL_UPLOAD.md
    ui/
      package.json, vite.config.ts, tsconfig.json, ...
      src/App.tsx
      src/components/Sidebar.tsx
      src/components/ChatMessage.tsx
      src/components/Composer.tsx
      src/components/EvidencePanel.tsx
      src/components/TracePanel.tsx
      src/lib/api.ts
      src/lib/types.ts
      src/styles.css
      tests/ ...
    tests/
      test_contracts.py
      test_entity_linking.py
      test_templates.py
      test_workflow.py
      test_grounding.py
      test_dataset.py
      test_eval_metrics.py
      test_api_fake.py
    scripts/
      setup.sh
      dev.sh
      check_env.py
      smoke_fake.sh
      smoke_ollama.sh
      smoke_neo4j.sh
      eval_synthetic.sh
    docs/
      DECISIONS.md
      LIMITATIONS.md
      OPERATIONS.md
      ACCEPTANCE_REPORT.md
      EXTERNAL_DEPENDENCIES.md
```

**Cấm:** tạo file empty/NotImplementedError/`TODO` thay cho chức năng cốt lõi, placeholder Python route không được nối, mock ngầm trong production, import sai. Những tính năng optional không thể chạy vì thiếu GPU/external auth phải có **code + dry-run + actionable instructions**, không bỏ file.

---

## 11. External dependencies & env — đừng bắt user đoán

Phải tạo `chatbot/.env.example`, `chatbot/docs/EXTERNAL_DEPENDENCIES.md` và `chatbot/scripts/check_env.py`. `check_env.py` in trạng thái `configured/missing/optional/unreachable` từng dịch vụ, **KHÔNG in giá trị secrets**. Chia 3 profile:

**A. FAKE (chạy được sau khi cài dependencies, không cần external secrets/online APIs):** `APP_MODE=fake`, `GRAPH_PROVIDER=fake`, `LLM_PROVIDER=fake`; đủ chạy UI/API/tests/dataset/eval synthetic. Không bắt Hugging Face/Aura/LangSmith.

**B. LIVE CPU BASE (cần AuraDB + Ollama):** `APP_MODE=real`, `GRAPH_PROVIDER=neo4j`, `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:0.6b`, `NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io`, `NEO4J_USERNAME=neo4j` hoặc readonly username, `NEO4J_PASSWORD=<user-filled>`, `NEO4J_DATABASE=neo4j`, `NEO4J_SCOPE_ID=nlpgraph-v1`. `HUGGING_FACE_TOKEN` **không cần** cho Ollama public baseline.

**C. LIVE CPU SFT (sau khi train):** như B nhưng `LLM_PROVIDER=hf_cpu`, `HF_MODEL_ID=Qwen/Qwen3-0.6B`, `MODEL_ADAPTER_PATH=/absolute/path/to/adapter`, `HF_HOME=/path/to/cache` optional, `DEVICE=cpu`, `USE_ADAPTER=true`; Qwen base có thể tải công khai 1 lần khi được network. `HF_TOKEN` chỉ optional cho private artifacts/rate limits/upload được owner phê duyệt.

**Các biến khác:** `API_HOST`, `API_PORT`, `WEB_PORT`, `FRONTEND_ORIGIN`, `MAX_ITERATIONS=5`, `MAX_RECORDS_PER_QUERY=20`, `MAX_GRAPH_HOPS=4`, `REQUEST_TIMEOUT_SECONDS`, `OLLAMA_TIMEOUT_SECONDS`, `DATASET_ROOT`, `EVAL_OUTPUT_DIR`, `LOG_LEVEL`, `DEBUG_TRACES`, `ENABLE_SSE`, `ENABLE_EXTERNAL_LLM_AUGMENT=false`; `LANGSMITH_TRACING=false` optional but NOT require `LANGSMITH_API_KEY` and not include it as mandatory setup. Do not add analytics secrets.

**Secrets discipline:** sample `.env.example` chỉ placeholders; `.env`, weights, synthetic/real private outputs, nested cloned repos, audit logs có secrets phải gitignore. Check tracked `.env` accidentally. Never upload outputs automatically.

**Cài đặt/runbook bắt buộc:** Ubuntu commands `uv sync`/`pip`, Node/npm, Ollama install/pull, start API, start frontend, run smoke; tại sao model CPU, HF adapter local; cách đổi profile bằng env, cách dùng `uv run python ...`; cách xử lý Aura TLS, timeout, memory shortage, no GPU, no Ollama, data mismatch. Setup không được tự phá virtualenv `offline/`.

---

## 12. Acceptance criteria & tự chạy/fix/test cho đến xong

**A. Local Fake profile (PHẢI PASS, không GPU/DB/online API; có thể cần Internet một lần để cài dependencies):**

- Backend start; `GET /api/health` phản ánh `fake`; `POST /api/chat` ít nhất 6 câu hỏi synthetic trả answer/status/sources/trace đúng schema; có 1-hop, multi-hop, ambiguous, no-result, partial.
- Max iterations never >5; all Cypher templates đều có tests parameterization/scope/typed output; fake/real không mix.
- UI `npm install`/lockfile, `npm run build` thành công; interface React có sidebar/composer/chat/evidence/trace; gọi fake backend được; mobile style; typed API.
- `pytest -q` toàn bộ test chatbot pass; dữ liệu synthetic reviewer export/import, split checker, sample SFT + eval synthetic runner pass. Reports gắn synthetic clearly.
- Training notebook parse JSON, có cell dry-run kiểm thư viện/schema, CLI `train_sft.py --dry-run` chạy được **không GPU và không cần weights**; actual training gated, không bị fake thành trained.
- README đúng commands. `git status` chỉ các file dự kiến; không secrets, no giant cloned repo tracked, `offline` tests không regress.

**B. Live optional (chỉ chạy khi resources available):**

- Có AuraDB: `verify_connectivity`, inventory labels/rel types/scope, sample read-only queries đúng schema và output evidence. Nếu thiếu credentials, **mark NOT RUN**; không fail toàn bộ test.
- Có Ollama/qwen3:0.6b: parse/answer 1–2 câu thật; nếu model không tải được, mark NOT RUN with exact setup command; đừng dùng fake output và gọi là real.
- Có adapter LoRA: load local PEFT trên CPU và 1 inference smoke, nếu không có adapter `B2 NOT RUN`.
- Có GPU/approved reviewed data: test SFT 1–2 steps (ở Colab), nếu không `TRAIN NOT RUN`; notebook ready.

**C. E2E/quality gates:**

- `pytest`; `ruff check`; type-check nếu configured; `npm run build`; optionally `npm run test` frontend; API smoke curl/httpx; UI smoke browser nếu available. Không suppress errors bằng generic `try/except: pass` hoặc mark pytest xfail hàng loạt.
- `chatbot/docs/ACCEPTANCE_REPORT.md` ghi: commands đã chạy, exit status, output excerpts, bao nhiêu tests pass/fail/skipped, fake/real phân loại, blockers, files produced, caveats, how to reproduce. Không viết số liệu bằng trí tưởng tượng.
- `chatbot/README.md` ngắn gọn cho user: setup FAKE để thấy UI ngay; chuyển Ollama + Aura; sau này chạy dataset generator/review, train notebook Colab, local adapter inference, chạy evaluation B0/B1/B2.

### 12.1 Lệnh nghiệm thu mong muốn (điều chỉnh theo package layout đã tạo)

```bash
# ở root mxh, sau khi setup deps đúng theo README
cd chatbot
bash scripts/check_env.sh 2>/dev/null || python scripts/check_env.py
bash scripts/smoke_fake.sh
python -m pytest -q
python -m ruff check .
cd ui && npm run build

# OPTIONAL ONLY WHEN AURA + OLLAMA PRESENT
# bash scripts/smoke_neo4j.sh
# bash scripts/smoke_ollama.sh

# FUTURE USER ACTIONS, must already be implemented:
# python datasets/generate_from_graph.py --provider neo4j --execute --out ...
# python datasets/export_review.py --input ... --out ...
# python datasets/import_review.py --csv ... --out ...
# python datasets/build_sft.py --reviewed ... --out ...
# python training/train_sft.py --dry-run --config training/config_sft.yaml
# python evaluation/run_eval.py --dataset ... --provider ollama --graph neo4j --max-iterations 5
```

**Lưu ý:** lệnh thực tế cuối cùng phải tồn tại và chạy được theo README. Không nhất thiết giữ đúng các dòng ví dụ nếu packaging đã chọn khác, nhưng phải có equivalent working commands.

---

## 13. Execution protocol — làm toàn bộ, không chỉ báo kế hoạch

**Phase 0 — Audit:** chạy inspect commands, đọc files, check repo tree và xác nhận baseline. Xuất `AUDIT.md` tóm tắt code đã có và điểm chạm. Không chỉ nhắn “đang làm” rồi dừng.

**Phase 1 — Working Fake Vertical Slice:** viết `settings/models/graph fake/llm fake/templates/planner/workflow/FastAPI`, tests 1-hop/multi-hop → `smoke_fake.sh` pass. Đây là **ưu tiên cao nhất** để hệ thống chạy được ngay và không block bởi GPU/Aura.

**Phase 2 — Read-only Neo4j and Qwen CPU:** implement `Neo4jGraphRepository`/entity linker, Ollama + HF CPU adapters, validation/citations, tests; optional live smoke if configured. Không đợi GPU.

**Phase 3 — Modern web UI:** implement React/Vite/TS frontend đầy đủ, API client + working E2E, UI state/errors/trace/source. Test/build.

**Phase 4 — Data & eval tooling:** implement tất cả generator/review/split/export/metrics/eval/compare + synthetic smoke. Có code tạo candidate & gold **khi human review trong tương lai**; không tự giả benchmark.

**Phase 5 — SFT setup:** notebook Colab hoàn chỉnh + shared training CLI + GPU gates + local PEFT adapter provider smoke. Không train thật trên laptop; không tự upload HF.

**Phase 6 — Repair and deliver:** chạy test loops, sửa lỗi, cập nhật architecture/readme/env/acceptance report, kiểm `git diff --stat`, `git status`, đưa **liệt kê cụ thể path mới + lệnh chạy + status fake/live/train**. Nếu đủ quyền và được owner yêu cầu riêng thì commit; **không push** mặc định.

**Đầu ra cuối BẮT BUỘC**: code đầy đủ và đã lưu ở filesystem, UI chạy bằng fake ngay, script test pass trong phạm vi tài nguyên, tài liệu external dependencies, notebook SFT, dataset generation/review/eval code, các blocker thật sự còn lại. Không nhận câu trả lời cuối chỉ chứa architecture, tên file, “hướng dẫn tự viết”, hoặc tự nhận pass không có log.

---

## 14. Tham chiếu uy tín / chỗ cần tra trước khi code theo phiên bản thư viện

- Repo chủ: `https://github.com/Hungpham715/mxh`
- Team 5: `https://github.com/Hungpham715/mxh/blob/main/references/team_5.md`
- Team 6: `https://github.com/Hungpham715/mxh/blob/main/references/team_6.md`
- Schema: `https://github.com/Hungpham715/mxh/blob/main/offline/docs/schema.md`
- Derivation: `https://github.com/Hungpham715/mxh/blob/main/offline/src/graph/derive.py`
- Model: `https://huggingface.co/Qwen/Qwen3-0.6B`
- Local CPU Ollama: `https://ollama.com/library/qwen3:0.6b`
- Ollama chat API: `https://docs.ollama.com/api/chat` (kiểm tra đường dẫn phiên bản hiện hành)
- Hugging Face TRL: `https://huggingface.co/docs/trl/sft_trainer`
- Hugging Face PEFT: `https://huggingface.co/docs/peft/index`
- Neo4j Python: `https://neo4j.com/docs/python-manual/current/`
- Google Colab FAQ: `https://research.google.com/colaboratory/faq.html`

**Version discipline:** kiểm API hiện hành và lock dependencies trước khi cài; không copy pseudo-API cũ khi TRL/Transformers thay đổi. Kiểm `python --version`, node version, available CUDA. Nếu internet bị chặn, viết adapter có unit tests mock và document no-live-blocker; không sử dụng package placeholder.

**BẮT ĐẦU THỰC THI NGAY** với Phase 0, rồi liên tục thực hiện Phase 1–6. Không hỏi lại những quyết định đã chốt trong prompt; không tự thêm công nghệ trái ràng buộc.
