"""Build the Vietnamese report (report/final.pdf + final.md + sections/*.md) from REAL output files only."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.common import EVAL, OUTPUT, PROCESSED, RAW, REJECTED, ROOT, log, read_json, read_jsonl
from src.graph.derive import REL_TYPES
from src.report.doc import Doc

AN = OUTPUT / "analysis"
NEO = OUTPUT / "neo4j"


def _j(path: Path) -> Any:
    return read_json(path) if path.exists() else None


def _fmt(x: Any) -> str:
    if isinstance(x, float):
        return f"{x:.4f}".rstrip("0").rstrip(".")
    if isinstance(x, int):
        return f"{x:,}".replace(",", ".")
    return "" if x is None else str(x)


REL_VI = {
    "FIRST_AUTHOR_OF": ("Author→Paper", "Tác giả đứng tên vị trí 1 trên bài (không khẳng định đóng góp lớn nhất)."),
    "OTHER_AUTHOR_OF": ("Author→Paper", "Tác giả đứng tên vị trí > 1."),
    "COAUTHORED_WITH": ("Author—Author", "Hai ID tác giả khác nhau cùng một bài; một cặp vô hướng (min_id,max_id), lưu paper_ids, shared_count."),
    "AFFILIATED_WITH": ("Author→Institution", "Tổ chức khai báo trong authorship của chính bài đó (OpenAlex), không phải nơi làm việc hiện tại."),
    "APPEARS_IN": ("Paper→Venue", "Volume ACL/EMNLP hoặc arXiv cs.CL (preprint)."),
    "HAS_TOPIC": ("Paper→Topic", "Luật title/abstract có span chứng cứ; tối đa 2 nhãn."),
    "CITES": ("Paper→Paper", "Paper X trích dẫn Y, cả hai trong corpus, theo referenced_works của X."),
    "ORG_COAUTHORED_WITH": ("Institution—Institution", "Hai tổ chức khác nhau do hai tác giả khác nhau khai báo trên cùng một bài."),
    "RESEARCHES": ("Author→Topic", "Tác giả có ≥ 2 bài khác nhau mang nhãn topic đó trong corpus."),
    "ACTIVE_IN": ("Institution→Topic", "Tổ chức có ≥ 2 bài khác nhau (có tác giả khai báo tổ chức) mang topic đó."),
}


def build_report(out_pdf: Path) -> int:
    manifest = _j(PROCESSED / "manifest.json")
    if manifest is None:
        log.error("no data/processed/manifest.json: run prepare first")
        return 2
    counts = _j(AN / "graph_counts.json") or {}
    net = _j(AN / "author_network.json") or {}
    sw = net.get("small_world") or {}
    imp = _j(NEO / "import_report_latest.json")
    imp2 = _j(NEO / "idempotency_check.json")
    pre = _j(NEO / "preflight.json")
    scores = _j(EVAL / "scores.json") or {}
    scores_post = _j(EVAL / "scores_postfix.json")
    struct = _j(EVAL / "structural_checks.json") or {}
    audits = _j(EVAL / "source_audits.json") or {}
    queries = _j(NEO / "example_queries.json")
    papers = read_jsonl(PROCESSED / "papers.jsonl")
    authors = read_jsonl(PROCESSED / "authors.jsonl")
    topics = read_jsonl(PROCESSED / "paper_topics.jsonl")
    acl_stats = read_jsonl(RAW / "acl_selection_stats.jsonl") if (RAW / "acl_selection_stats.jsonl").exists() else []
    ns = manifest.get("normalize_stats", {})
    oc = manifest["output_counts"]
    n_acl = sum(1 for p in papers if p["source_kind"] == "acl")
    n_arx = len(papers) - n_acl
    n_alias = sum(1 for p in papers if p["source_kind"] == "acl" and p.get("arxiv_id"))
    status = Counter(a["identity_status"] for a in authors)
    tstat = manifest.get("topic_status_counts", {})
    tcount = Counter(t["topic_id"] for t in topics)
    total_nodes = counts.get("total_nodes")
    total_rels = counts.get("total_relationships")

    d = Doc()
    d.h1("Mạng lưới các tác giả và tổ chức nghiên cứu về Xử lý ngôn ngữ tự nhiên (NLP) quốc tế")
    d.p("<b>Báo cáo kỹ thuật</b> – dự án đồ thị tri thức đồng tác giả, tổ chức, chủ đề và trích dẫn xây dựng từ "
        "ACL Anthology, arXiv cs.CL và OpenAlex, lưu trữ trên Neo4j AuraDB. Tất cả số liệu trong báo cáo được sinh tự động "
        f"từ các tệp đầu ra thật của pipeline (manifest tạo lúc {manifest['created_at_utc']}, scope_id "
        f"<b>{manifest['scope_id']}</b>). Không có số liệu nào được điền tay.")
    d.p("<i>Ghi chú về tác giả báo cáo:</i> mã nguồn, dữ liệu và báo cáo được thực hiện bởi một tác tử lập trình tự động "
        "theo đặc tả architecture.md và prompt.md; báo cáo không ghi tên thành viên hay tỷ lệ phân công vì không có thông tin "
        "đó được cung cấp.")

    # ---------------------------------------------------------------- 1
    d.h2("1. Đề bài, phạm vi và tiêu chí đo được")
    d.p("Đề bài: “Mạng lưới các tác giả và tổ chức nghiên cứu về Xử lý ngôn ngữ tự nhiên (NLP) Quốc tế”, liên kết công bố "
        "khoa học, tác giả, tổ chức được khai báo và trích dẫn từ ACL/arXiv. Câu hỏi trung tâm mà hệ thống phải trả lời là: "
        "<i>hai tác giả A và B đã viết chung bài nào, khi viết bài đó mỗi người khai báo tổ chức nào, các bài ấy thuộc chủ đề gì "
        "và họ nằm trong cộng đồng nghiên cứu nào?</i> – và mọi câu trả lời phải truy ngược được tới paper ID và URL nguồn.")
    d.p("Văn bản đề gốc ghi ngưỡng “2000 nghìn nút”, cách viết này mơ hồ (2.000 hay 2.000.000). Dự án chọn mức bảo thủ "
        "<b>≥ 2.000 nút, ≥ 5.000 cạnh duy nhất và đủ 10 loại quan hệ có dữ liệu thật</b>; cách hiểu này <b>chưa được giảng viên "
        "xác nhận</b> và được nêu lại ở phần kết luận.")
    rows = [
        ["Corpus 1.000–1.200 paper duy nhất", f"{_fmt(len(papers))} paper (ACL {_fmt(n_acl)}, arXiv {_fmt(n_arx)})",
         "Đạt" if 1000 <= len(papers) <= 1200 else "Chưa đạt"],
        ["≥ 2.000 nút", _fmt(total_nodes), "Đạt" if (total_nodes or 0) >= 2000 else "Chưa đạt"],
        ["≥ 5.000 cạnh duy nhất", _fmt(total_rels), "Đạt" if (total_rels or 0) >= 5000 else "Chưa đạt"],
        ["10/10 loại quan hệ có dữ liệu", f"{counts.get('populated_types')}/10", "Đạt" if counts.get("populated_types") == 10 else "Chưa đạt"],
        ["≥ 1.000 Author (đo riêng)", _fmt(len(authors)), "Đạt" if len(authors) >= 1000 else "Chưa đạt"],
        ["Graph trên Neo4j AuraDB", "Có" if imp else "Chưa import", "Đạt" if imp else "Chưa đạt"],
        ["Precision cạnh ≥ 90% (mỗi type & micro)", _precision_line(scores), "Xem mục 7"],
    ]
    d.table(["Tiêu chí", "Kết quả thực đo", "Trạng thái"], rows, [0.38, 0.40, 0.22])

    # ---------------------------------------------------------------- 2
    d.h2("2. Nguồn dữ liệu học thuật và quy tắc chọn mẫu cố định")
    d.p("Ba nguồn chính được dùng, đúng vai trò mô tả trong kiến trúc:")
    d.bullets([
        "<b>ACL Anthology</b> – tệp XML chính thức trong kho acl-org/acl-anthology (data/xml/&lt;collection&gt;.xml). "
        "Cung cấp ACL ID, tiêu đề, abstract, danh sách tác giả theo thứ tự, DOI và URL. Không scrape HTML.",
        "<b>arXiv API</b> (export.arxiv.org/api/query) – truy vấn cat:cs.CL theo từng tháng, User-Agent có thông tin liên hệ, "
        "giãn cách 3,5 giây giữa các yêu cầu, có cache.",
        "<b>OpenAlex</b> – tra cứu đúng một work theo DOI (/works/doi:&lt;DOI&gt;; với arXiv dùng DOI 10.48550/arxiv.&lt;id&gt;). "
        "Lấy authorships (tác giả, author_position, institutions theo từng bài), referenced_works và abstract_inverted_index.",
    ])
    d.p(f"Ngày chốt metadata: {manifest['source_versions'].get('acl_anthology', '')}. Quy tắc chọn được ghi trong "
        "configs/scope.yaml <b>trước</b> khi xem bất kỳ số liệu graph nào: với mỗi volume chính (ACL long / EMNLP main các năm "
        "2023–2025) lấy 140 bài bằng chọn hệ thống theo paper ID tăng dần (chỉ số floor(i·N/140)); Findings là phương án dự phòng "
        "nhưng không cần dùng vì mọi volume chính đều đủ số lượng. Với arXiv, mỗi tháng lấy 7 bài đầu tiên theo ngày nộp "
        "tăng dần có <i>primary category</i> là cs.CL.")
    if acl_stats:
        d.table(["Collection", "Volume", "Số bài có sẵn", "Đã chọn"],
                [[s["collection"], s["volume"], _fmt(s["available"]), _fmt(s["selected"])] for s in acl_stats],
                [0.3, 0.2, 0.25, 0.25])
    ic = manifest["input_counts"]
    d.p(f"Đầu vào: {_fmt(ic.get('acl_selected'))} bản ghi ACL, {_fmt(ic.get('arxiv_selected'))} bản ghi arXiv; "
        f"{_fmt(ic.get('openalex_matched'))}/{_fmt(ic.get('openalex_lookups'))} tra cứu OpenAlex khớp DOI. Sau khử trùng "
        f"còn {_fmt(len(papers))} paper; {_fmt(n_alias)} bản arXiv được xác định là cùng work OpenAlex với một bài ACL và được "
        "gộp làm alias (giữ bản hội nghị). Số paper không khớp OpenAlex: "
        f"{_fmt(manifest['unmatched_openalex_count'])}.")
    d.h3("Vì sao Wikipedia không phải nguồn chính")
    d.p("Wikipedia không có danh sách đồng tác giả theo từng bài, không có tổ chức khai báo theo từng công bố và không có "
        "danh sách trích dẫn theo bài; chỉ một phần nhỏ nhà nghiên cứu NLP có trang Wikipedia. Do đó các quan hệ cần chứng cứ "
        "theo bài (đồng tác giả, affiliation theo authorship, citation) phải lấy từ nguồn thư mục học (ACL Anthology, arXiv, "
        "OpenAlex). Wikipedia chỉ phù hợp để đối chiếu thủ công tên tổ chức khi nghi ngờ, và dự án này không cần dùng tới.")

    # ---------------------------------------------------------------- 3
    d.h2("3. Thu thập, chuẩn hóa, định danh và NLP")
    d.p("Pipeline: <b>fetch</b> (ACL XML, arXiv Atom, OpenAlex JSON, tất cả có cache và nhật ký yêu cầu) → <b>prepare</b> "
        "(chuẩn hóa ID, khử trùng, gán định danh tác giả, phân loại chủ đề, xuất 8 tệp JSONL + manifest có SHA-256) → "
        "<b>validate</b> (kiểm schema, khóa, khóa ngoại, span chủ đề, checksum) → <b>import</b> lên Neo4j.")
    d.h3("Định danh và khử trùng")
    d.bullets([
        "Paper: ưu tiên OpenAlex W-id (oa:W…); nếu không khớp dùng acl:&lt;id&gt; hoặc arxiv:&lt;id&gt;. Không gộp theo tiêu đề gần giống; "
        "trường hợp mơ hồ ghi vào data/rejected/unresolved.csv.",
        "Tác giả: chỉ nhận OpenAlex A-id khi số tác giả nguồn bằng số authorship OpenAlex <b>và</b> họ tên ở cùng vị trí tương thích. "
        "Ngược lại tác giả nhận ID cục bộ src:&lt;paper&gt;#&lt;vị trí&gt;, chỉ tồn tại trong một bài nên không bao giờ tạo cạnh xuyên bài "
        "chỉ vì trùng tên.",
        "Affiliation: chỉ lấy authorships[].institutions của đúng bài, không dùng last_known_institutions; không suy từ email.",
        "Citation: chỉ giữ khi cả bài trích dẫn và bài được trích đều nằm trong corpus và khác nhau.",
    ])
    d.table(["Chỉ số chuẩn hóa", "Giá trị"], [
        ["Authorship gán OpenAlex ID đã kiểm (verified)", _fmt(ns.get("authorship_verified"))],
        ["Authorship chỉ theo nguồn (source_only)", _fmt(ns.get("authorship_source_only"))],
        ["Authorship lệch tên với OpenAlex (unresolved)", _fmt(ns.get("authorship_unresolved"))],
        ["Bài lệch số tác giả nguồn vs OpenAlex", _fmt(ns.get("authorship_count_mismatch"))],
        ["Authorship verified nhưng không có institution", _fmt(ns.get("verified_authorship_without_institution"))],
        ["Bài có referenced_works", _fmt(ns.get("papers_with_references"))],
        ["Bài thiếu abstract", _fmt(ns.get("missing_abstract"))],
        ["Node Author theo trạng thái", ", ".join(f"{k}: {_fmt(v)}" for k, v in sorted(status.items()))],
    ], [0.6, 0.4])
    d.h3("Phân loại chủ đề bằng luật")
    d.p("Đầu vào là title + \\n + abstract, chuẩn hóa Unicode NFKC, chữ thường, gom khoảng trắng. Mỗi mẫu là một regex có "
        "ranh giới từ (ví dụ \\brag\\b không khớp “fragment”). Khớp ở tiêu đề được 2 điểm, ở abstract 1 điểm (mỗi topic tối đa "
        "một lần mỗi trường), ngưỡng 2, tối đa 2 topic; hòa điểm ở vị trí cuối thì không gán topic hòa và đưa vào rà tay. "
        f"Phiên bản luật: <b>{manifest.get('topic_rule_version')}</b> (configs/topics.yaml). Không dùng embedding, mô hình học máy "
        "hay API LLM.")
    d.table(["Topic", "Số bài gán"], [[t, _fmt(tcount.get(t, 0))] for t in ("llm", "mt", "qa", "retrieval", "summarization", "safety_eval")]
            + [["UNKNOWN (không topic)", _fmt(tstat.get("UNKNOWN", 0))], ["tie_review", _fmt(tstat.get("tie_review", 0))]],
            [0.6, 0.4])
    ex = _topic_examples(papers, topics)
    if ex:
        d.p("Ví dụ thật từ corpus (span chứng cứ trích nguyên văn):")
        d.bullets(ex)
    pilot = _j(EVAL / "topic_pilot.json")
    if pilot:
        d.p(f"Pilot luật: {pilot.get('n')} bài đầu tiên theo ID đã được xem trước khi lấy mẫu đánh giá; "
            f"{pilot.get('summary', '')}")

    # ---------------------------------------------------------------- 4
    d.h2("4. Hợp đồng dữ liệu JSONL v1 và schema Neo4j")
    d.p("Thư mục data/processed/ gồm đúng 8 tệp JSONL UTF-8 (mỗi dòng một đối tượng JSON) và manifest.json được ghi cuối cùng. "
        "Bộ nạp chỉ chạy khi đủ tệp, đúng schema và đúng checksum.")
    d.table(["Tệp", "Số dòng", "SHA-256 (16 ký tự đầu)"],
            [[f, _fmt(oc[f]), manifest["checksums"][f][:16]] for f in oc], [0.4, 0.2, 0.4])
    sample_paper = next((p for p in papers if p["source_kind"] == "acl" and p.get("openalex_id")), papers[0])
    d.p("Ví dụ một dòng papers.jsonl thật (abstract rút gọn):")
    sp = dict(sample_paper)
    if sp.get("abstract"):
        sp["abstract"] = sp["abstract"][:140] + "…"
    sp.pop("alias_source_urls", None)
    d.code(json.dumps(sp, ensure_ascii=False, indent=1)[:1500])
    d.h3("5 nhãn nút và 10 loại quan hệ")
    d.table(["Nhãn", "Số nút"], [[k, _fmt(v)] for k, v in counts.get("nodes", {}).items()], [0.5, 0.5])
    d.table(["#", "Quan hệ", "Cặp nút", "Điều kiện / ý nghĩa", "Số cạnh", "Paper làm chứng"],
            [[str(i), t, REL_VI[t][0], REL_VI[t][1], _fmt(counts.get("relationships", {}).get(t)),
              _fmt(counts.get("evidence_papers_by_type", {}).get(t))] for i, t in enumerate(REL_TYPES, 1)],
            [0.04, 0.2, 0.15, 0.39, 0.1, 0.12])
    d.p("Mọi quan hệ lưu source_kind, source_url, evidence_paper_ids, evidence_count, first_year/last_year và build_version. "
        "Số quan hệ và số paper làm bằng chứng được báo riêng, không cộng lẫn. Bài có hơn 20 tác giả không sinh clique "
        f"đồng tác giả mà được đưa vào danh sách rà tay ({_count_lines(REJECTED / 'large_author_papers.jsonl')} bài).")
    d.img(AN / "relationship_types.png", "Hình 1. Số cạnh duy nhất theo loại quan hệ (snapshot thật).", 15)

    # ---------------------------------------------------------------- 5
    d.h2("5. Công nghệ, kết nối AuraDB và quyết định thiết kế")
    d.bullets([
        "Python 3.13 quản lý bằng uv (pyproject.toml + uv.lock): httpx, pydantic, neo4j (driver chính thức), networkx, matplotlib, "
        "PyYAML, python-dotenv, reportlab, pytest.",
        "Neo4j AuraDB (instance có sẵn của người dùng), kết nối URI neo4j+s:// (TLS) bằng user/password đọc từ .env "
        "(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE). Không có mật khẩu nào trong mã nguồn, log hay báo cáo.",
        "An toàn cloud: chỉ MERGE theo ID ổn định, gắn scope_id = nlpgraph-v1 lên mọi nút/cạnh của dự án; trước khi ghi kiểm tra "
        "xung đột ID với dữ liệu không thuộc dự án; tuyệt đối không có lệnh DELETE/DROP trong mã.",
        "Kiểu quan hệ lấy từ whitelist 10 tên cố định, Cypher tham số hóa UNWIND $rows theo lô 300 dòng, có retry cho lỗi tạm thời.",
        "Các cạnh suy diễn được tính một lần trong Python từ snapshot đã kiểm (src/graph/derive.py) rồi nạp lên Neo4j; "
        "nhờ vậy phân tích cục bộ và graph trên cloud dùng đúng một tập cạnh.",
    ])
    if pre:
        d.p(f"Preflight AuraDB: RETURN 1 = {pre.get('return_1')}, máy chủ {pre.get('server_agent')}; trước import instance có "
            f"{_fmt(pre.get('total_nodes'))} nút và {_fmt(pre.get('total_relationships'))} quan hệ "
            f"({_fmt(pre.get('foreign_nodes'))} nút không thuộc dự án).")
    else:
        d.p("<b>Preflight AuraDB chưa chạy được</b> (thiếu thông tin đăng nhập trong .env tại thời điểm tạo báo cáo).")

    # ---------------------------------------------------------------- 6
    d.h2("6. Graph trên AuraDB và phân tích mạng đồng tác giả")
    if imp:
        v = imp["verified"]
        d.p(f"Import hoàn tất lúc {imp['finished_at_utc']} trong {imp['seconds']} giây. Đếm lại trên AuraDB (lọc scope_id): "
            f"<b>{_fmt(v['project_nodes'])} nút</b>, <b>{_fmt(v['project_relationships'])} quan hệ</b>, "
            f"{v['populated_types']}/10 loại có dữ liệu, {v['parallel_duplicate_pairs']} cặp cạnh song song trùng lặp, "
            f"{v['relationships_without_evidence']} quan hệ thiếu evidence.")
        d.table(["Quan hệ", "Kế hoạch", "Đếm trên AuraDB"],
                [[t, _fmt(imp["plan"]["relationships"][t]), _fmt(v["relationships_by_type"][t])] for t in REL_TYPES],
                [0.4, 0.3, 0.3])
        if imp2:
            d.p(f"Kiểm tra idempotency: nạp lại cùng snapshot lần hai cho số nút/cạnh "
                f"{'<b>giống hệt</b>' if imp2.get('identical') else '<b>KHÁC</b>'} "
                f"({_fmt(imp2['first']['project_nodes'])}/{_fmt(imp2['first']['project_relationships'])} → "
                f"{_fmt(imp2['second']['project_nodes'])}/{_fmt(imp2['second']['project_relationships'])}).")
    else:
        d.p("<b>Chưa import lên AuraDB</b>; các số dưới đây tính từ snapshot cục bộ, cùng tập cạnh sẽ được nạp.")
    if queries:
        d.h3("Truy vấn Cypher minh họa (chạy thật trên AuraDB)")
        for q in queries:
            d.p(f"<b>{q['title']}</b>")
            d.code(q["cypher"])
            if q.get("rows"):
                d.code("\n".join(json.dumps(r, ensure_ascii=False)[:200] for r in q["rows"][:5]))
    st = net.get("stats", {})
    d.h3("Phép chiếu Author–Author")
    d.p("Phân tích mạng chỉ dùng đồ thị vô hướng, đơn Author—COAUTHORED_WITH—Author (trọng số = số bài chung); không đi qua "
        "Venue/Topic/Institution.")
    d.table(["Chỉ số", "Giá trị"], [
        ["Số tác giả (tất cả, kể cả cô lập)", _fmt(st.get("authors_total"))], ["Số cạnh đồng tác giả", _fmt(st.get("edges"))],
        ["Tác giả cô lập", _fmt(st.get("isolates"))], ["Thành phần liên thông", _fmt(st.get("connected_components"))],
        ["Kích thước LCC", _fmt(st.get("lcc_size"))], ["Tỷ lệ LCC trên toàn bộ Author", _fmt(st.get("lcc_ratio_of_all_authors"))],
        ["Bậc trung bình", _fmt(st.get("mean_degree"))], ["10 thành phần lớn nhất", ", ".join(map(str, st.get("component_size_top10", [])))],
    ], [0.55, 0.45])
    d.p("Phần lớn tác giả cô lập là tác giả source_only/unresolved (định danh chỉ trong một bài) và tác giả của bài đơn tác giả; "
        "corpus là mẫu ~1.100 bài nên mạng bị phân mảnh mạnh – đây là đặc điểm của mẫu, không phải của cộng đồng NLP thật.")
    d.img(AN / "degree_distribution.png", "Hình 2. Phân bố bậc của phép chiếu tác giả (log-log).", 12)
    if net.get("top10_pagerank"):
        d.h3("Top 10 tác giả theo PageRank và bậc")
        d.table(["#", "Tác giả", "PageRank", "Bậc", "Bậc có trọng số", "Ví dụ paper chứng cứ"],
                [[str(i), r["name"], f"{r['score']:.5f}", str(r["degree"]), str(r["weighted_degree"]), ", ".join(r["evidence_paper_ids"][:2])]
                 for i, r in enumerate(net["top10_pagerank"], 1)], [0.04, 0.24, 0.12, 0.08, 0.12, 0.40])
        d.p("Bậc = số đồng tác giả khác nhau; bậc có trọng số = tổng số lần viết chung. PageRank ở đây là độ trung tâm cấu trúc "
            "trong mẫu, không phải thước đo năng lực khoa học.")
    cm_ = net.get("communities", {})
    if cm_:
        d.h3("Cộng đồng (Louvain)")
        d.p(f"Phương pháp: {cm_.get('method')}, seed {cm_.get('seed')}, xét {_fmt(cm_.get('nodes_considered'))} tác giả có ít nhất "
            f"một cạnh: <b>{_fmt(cm_.get('n_communities'))} cộng đồng</b>, modularity <b>{cm_.get('modularity')}</b>. Kích thước "
            f"10 cộng đồng lớn nhất: {', '.join(map(str, cm_.get('size_top10', [])))}.")
        d.table(["Cộng đồng", "Số tác giả", "Số bài", "Topic chính", "Thành viên tiêu biểu"],
                [[str(c["community"]), str(c["size"]), str(c["papers"]), ", ".join(f"{t}({n})" for t, n in c["top_topics"]) or "–",
                  ", ".join(c["members_sample"][:4])] for c in net.get("community_summary", [])[:6]],
                [0.1, 0.1, 0.08, 0.27, 0.45])
    d.img(AN / "ego_top_pagerank.png", "Hình 3. Mạng con quanh tác giả có PageRank cao nhất (màu = cộng đồng Louvain).", 14)
    pe = net.get("shortest_path_example")
    if pe:
        d.h3("Đường đi ngắn nhất có chứng cứ")
        d.p(f"Ví dụ đường ngắn nhất độ dài {pe['length']} giữa hai tác giả trong LCC; mỗi bước liệt kê bài viết chung:")
        d.bullets([f"{h['from_name']} — {h['to_name']}: “{h['evidence_titles'][0]}” ({h['evidence_urls'][0]})" for h in pe["hops"]])
    d.h3("Kiểm tra small-world")
    if sw.get("status") == "computed":
        d.table(["Đại lượng", "Giá trị"], [
            ["LCC (nút / cạnh)", f"{_fmt(sw['lcc_nodes'])} / {_fmt(sw['lcc_edges'])}"],
            ["C_obs (average clustering)", _fmt(sw["C_obs"])], ["L_obs (average shortest path)", f"{_fmt(sw['L_obs'])} ({sw['L_method']})"],
            ["C_rand (TB {} đồ thị ngẫu nhiên)".format(sw["n_random"]), _fmt(sw["C_rand"])], ["L_rand", _fmt(sw["L_rand"])],
            ["σ = (C_obs/C_rand)/(L_obs/L_rand)", _fmt(sw["sigma"])], ["Kết luận", sw["verdict"]],
        ], [0.5, 0.5])
        d.p("Đồ thị ngẫu nhiên giữ nguyên dãy bậc bằng hoán đổi cạnh kép (10·m lần), 5 seed cố định. Hạn chế: " +
            "; ".join(sw.get("limitations", [])) + ". Không có kiểm định thống kê nên σ chỉ mang tính mô tả.")
        d.img(AN / "small_world.png", "Hình 4. C và L của LCC so với đồ thị ngẫu nhiên giữ bậc.", 13)
    else:
        d.p(f"Không xác định: {sw.get('reason')}")

    # ---------------------------------------------------------------- 7
    d.h2("7. Kiểm tra chất lượng và tiêu chí 90%")
    d.p("Chất lượng cạnh đo bằng <b>precision</b> = cạnh đúng / cạnh được kiểm. Quy trình: (1) kiểm tra cấu trúc <b>mọi</b> cạnh "
        "(đúng kiểu nút hai đầu, có evidence, không trùng, cặp vô hướng chuẩn hóa, ngưỡng ≥ 2 bài, chiều trích dẫn); "
        "(2) lấy mẫu phân tầng tối đa 20 cạnh mỗi loại với seed 20261107; (3) kiểm chứng lại từng cạnh mẫu với bản ghi nguồn gốc "
        "(XML ACL, feed arXiv, JSON work OpenAlex được lưu cache) – độc lập với tệp JSONL đã xử lý.")
    bad_struct = sum(v.get("invalid", 0) for v in struct.values())
    d.p(f"Kiểm tra cấu trúc: {_fmt(sum(v.get('checked', 0) for v in struct.values()))} cạnh được kiểm, "
        f"<b>{_fmt(bad_struct)}</b> cạnh vi phạm.")
    a = scores.get("automated_preliminary")
    if a:
        d.p("<b>Lưu ý quan trọng:</b> nhãn dưới đây là <i>automated_preliminary</i> – do chương trình tự đối chiếu với nguồn, "
            "<b>không phải</b> gán nhãn độc lập của con người. Chưa có nhãn người (tệp evaluation/labels.csv chưa tồn tại), "
            "vì vậy precision do người kiểm <b>chưa được đo</b>; mẫu phiếu evaluation/manual_review_template.csv đã sẵn sàng.")
        _score_table(d, a)
    if scores_post and scores_post.get("automated_preliminary"):
        d.p("Sau khi sửa lỗi hệ thống (mục 7.1), lấy <b>mẫu mới</b> và đo lại:")
        _score_table(d, scores_post["automated_preliminary"])
    fixes = _j(EVAL / "fix_log.json")
    if fixes:
        d.h3("7.1 Lỗi phát hiện và sửa")
        d.bullets([f"{f['issue']} → {f['fix']}" for f in fixes])
    if audits:
        d.h3("7.2 Các kiểm tra nguồn bổ sung")
        d.table(["Kiểm tra", "Kết quả"], [[k, str(v)] for k, v in audits.items()], [0.45, 0.55])
    d.p("Với 20 mẫu/loại, ngay cả 20/20 đúng thì cận dưới Wilson 95% cũng chỉ ≈ 0,84, nên <b>không thể khẳng định chắc chắn ≥ 90%</b>; "
        "các con số trên là ước lượng điểm kèm khoảng tin cậy.")

    # ---------------------------------------------------------------- 8
    d.h2("8. Kết luận, hạn chế và cách tái hiện")
    d.p("Đạt được: pipeline tái hiện được từ nguồn thật tới graph, 10 loại quan hệ có dữ liệu và chứng cứ theo bài, phân tích "
        "mạng tác giả với baseline ngẫu nhiên, đánh giá chất lượng có khoảng tin cậy và lưu vết.")
    d.bullets([
        "Phép chiếu tác giả bị phân mảnh do lấy mẫu ~1.100 bài trên hàng chục nghìn bài; mạng thật dày hơn nhiều.",
        "Tác giả không khớp OpenAlex được giữ ở mức một bài (source_only), làm giảm số cạnh xuyên bài nhưng tránh gộp nhầm.",
        "Citation chỉ là trích dẫn nội bộ corpus, không đo toàn bộ ảnh hưởng học thuật.",
        "Phân loại chủ đề bằng luật có độ bao phủ hạn chế (nhiều bài UNKNOWN) – chấp nhận để giữ precision.",
        "ORG_COAUTHORED_WITH là đồng xuất hiện trên bài, không phải thỏa thuận hợp tác; ACTIVE_IN chỉ xét trong corpus.",
        "Ngưỡng “2000 nghìn nút” chưa được giảng viên xác nhận; precision theo người gán nhãn chưa đo.",
    ])
    d.p("Lệnh tái hiện (cần .env với các biến ở mục 5):")
    d.code("uv sync\nuv run pytest -q\nuv run python -m src.cli fetch --config configs/scope.yaml\n"
           "uv run python -m src.cli prepare --config configs/topics.yaml\nuv run python -m src.cli validate --data data/processed\n"
           "uv run python -m src.cli import --data data/processed --dry-run\nuv run python -m src.cli import --data data/processed\n"
           "uv run python -m src.cli analyze --out output/analysis\nuv run python -m src.cli sample --per-type 20 --seed 20261107\n"
           "uv run python -m src.cli score --labels evaluation/labels.csv\nuv run python -m src.cli report --out report/final.pdf")
    d.p(f"Hash manifest: papers.jsonl SHA-256 = {manifest['checksums']['papers.jsonl']}. Link GitHub: chưa có (repo chỉ ở máy cục bộ).")
    d.p("Tài liệu tham khảo: ACL Anthology (aclanthology.org/faq/api), arXiv API User Manual (info.arxiv.org/help/api), "
        "OpenAlex Works/Authorships/Topics (help.openalex.org), Neo4j Python Driver Manual, NetworkX small-world reference.")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    md = d.to_markdown(out_pdf.parent)
    (out_pdf.parent / "final.md").write_text(md, encoding="utf-8")
    _write_sections(md, out_pdf.parent / "sections")
    pages = d.to_pdf(out_pdf, "Mạng tác giả & tổ chức NLP – nlpgraph-v1")
    log.info("report written: %s (%d pages)", out_pdf, pages)
    print(f"report: {out_pdf} pages={pages}")
    return 0


def _precision_line(scores: dict[str, Any]) -> str:
    a = scores.get("automated_preliminary")
    if "human" in scores:
        h = scores["human"]
        return f"người kiểm: micro {h['micro_precision_weighted']}"
    if a:
        return f"Chưa có nhãn người; tự động sơ bộ micro {a['micro_precision_weighted']}"
    return "Chưa đo"


def _score_table(d: Doc, a: dict[str, Any]) -> None:
    rows = []
    for t, v in a["per_type"].items():
        if not v.get("n"):
            continue
        rows.append([t, _fmt(v["graph_count"]), str(v["n"]), str(v["correct"]), str(v["incorrect"]), str(v["unverifiable"]),
                     _fmt(v["precision"]), f"[{v['wilson95'][0]:.3f}; {v['wilson95'][1]:.3f}]"])
    d.table(["Loại", "Số cạnh graph", "Mẫu", "Đúng", "Sai", "Không kiểm được", "Precision", "Wilson 95%"], rows,
            [0.22, 0.12, 0.07, 0.07, 0.07, 0.13, 0.11, 0.21])
    ci = a.get("micro_ci95_stratified_wilson", a.get("micro_ci95_stratified_normal"))
    d.p(f"Precision macro = <b>{a['macro_precision']}</b>; precision micro có trọng số theo số cạnh mỗi loại trong graph = "
        f"<b>{a['micro_precision_weighted']}</b> (KTC 95% Wilson phân tầng {ci}). "
        f"Số loại có ước lượng điểm ≥ 0,90: {a['types_meeting_0.90_point_estimate']}/10; số loại có cận dưới Wilson ≥ 0,90: "
        f"{a['types_with_wilson_lower_ge_0.90']}/10. “Không kiểm được” được tính là không đúng.")


def _topic_examples(papers: list[dict[str, Any]], topics: list[dict[str, Any]]) -> list[str]:
    byp = {p["id"]: p for p in papers}
    out, seen = [], set()
    for t in topics:
        if t["topic_id"] in seen or ":title" not in t["rule_id"]:
            continue
        seen.add(t["topic_id"])
        p = byp[t["paper_id"]]
        out.append(f"[{t['topic_id']}] “{p['title']}” – span “{t['evidence_span']}” ({p['source_url']})")
        if len(out) >= 3:
            break
    return out


def _count_lines(p: Path) -> int:
    return sum(1 for _ in open(p, encoding="utf-8")) if p.exists() else 0


def _write_sections(md: str, sec: Path) -> None:
    sec.mkdir(parents=True, exist_ok=True)
    parts = md.split("\n## ")
    data = [p for p in parts if p.startswith(("2.", "3.", "4."))]
    graph = [p for p in parts if p.startswith(("5.", "6.", "7."))]
    (sec / "data.md").write_text("## " + "\n## ".join(data), encoding="utf-8")
    (sec / "graph.md").write_text("## " + "\n## ".join(graph), encoding="utf-8")
    _ = csv
