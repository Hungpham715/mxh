# Hướng dẫn gán nhãn thủ công: AFFILIATED_WITH, ORG_COAUTHORED_WITH, ACTIVE_IN

Phiên bản: guideline-v1 (2026-11-03). Áp dụng cho `review_sheet_round1.csv`, `review_sheet_round2.csv` và
`review_sheet_round1_overlap_reviewer2.csv`. Đọc hết tài liệu trước khi chấm dòng đầu tiên. Khi gặp trường hợp mà
tài liệu chưa nói rõ, ghi lại trong cột `note`, chọn nhãn theo nguyên tắc chung ở mục 1 và báo lại để bổ sung
guideline (không tự đổi quy tắc giữa chừng).

## 0. Nguyên tắc làm việc

1. **Nguồn sự thật là chính bài báo** (bản PDF ở cột `pdf_url`, hoặc trang ở `paper_url`). Cột `evidence_text` chỉ là
   trích dẫn từ metadata (ACL Anthology XML, OpenAlex) để giúp bạn tìm nhanh; nó **có thể sai**. Nếu PDF và
   `evidence_text` mâu thuẫn, tin PDF.
2. **Không mở** các tệp sau cho đến khi chấm xong: `evaluation/automated_labels*.csv`, `evaluation/scores*.json`,
   `evaluation/source_audits*.json`, `evaluation/fix_log.json`, `evaluation/sampling/`, `report/`. Chúng chứa kết quả
   kiểm tra tự động hoặc thông tin phân tầng có thể làm bạn bị ảnh hưởng.
3. Người chấm thứ hai (nếu có) chấm tệp `review_sheet_round1_overlap_reviewer2.csv` **độc lập**, không xem nhãn của
   người thứ nhất.
4. Chấm theo **định nghĩa của dự án** (mục 2–4), không theo hiểu biết chung về tổ chức. Ví dụ: một người nổi tiếng làm ở
   Google nhưng trên bài này chỉ ghi "Stanford University" thì cạnh tới Google là sai **đối với bài này**.
5. Mỗi dòng mất khoảng 1–5 phút. Nếu một dòng mất quá 10 phút, chọn `unverifiable` và ghi lý do.

## 1. Ba nhãn

| Nhãn | Khi nào dùng |
|---|---|
| `correct` | Đọc bài (các bài) được liệt kê, khẳng định của cạnh (định nghĩa ở mục 2–4) là **đúng**. |
| `incorrect` | Đọc được bài, và khẳng định của cạnh **sai** (sai tổ chức, sai người, sai ngưỡng, bằng chứng không ủng hộ). Bắt buộc điền `error_type`. |
| `unverifiable` | **Không thể** kiểm chứng: không mở được bài/PDF, bài không in affiliation ở đâu cả, tên trên bài quá mơ hồ để quyết định. Bắt buộc ghi lý do ở `note`. **Không** dùng `unverifiable` cho trường hợp "khó" mà bạn vẫn có thể quyết định được. |

Định dạng: viết thường, đúng chính tả như trên (`correct`, `incorrect`, `unverifiable`). Script chấp nhận khoảng trắng
thừa và chữ hoa, nhưng từ chối mọi giá trị khác.

Quy tắc điền cột:
- `label=correct` → để trống `error_type`.
- `label=incorrect` → `error_type` bắt buộc, chọn **một** giá trị trong danh sách ở mục 5.
- `label=unverifiable` → để trống `error_type`; `note` bắt buộc.
- `reviewer` bắt buộc ở mọi dòng (viết tắt tên, ví dụ `HL`). Giữ nguyên một cách viết suốt quá trình.
- `adjudicated_label`: chỉ điền sau khi hai người chấm bất đồng ở một dòng `is_overlap=1` (xem mục 7).

## 2. AFFILIATED_WITH (Author → Institution)

**Khẳng định của cạnh:** "Trên ít nhất một bài được liệt kê, tác giả `source_name` khai báo tổ chức `target_name`
(hoặc một đơn vị trực thuộc tổ chức đó, xem 6.2)". Cạnh **không** nói người đó *hiện đang* làm ở đó.

`correct` khi: mở bài, tìm đúng tác giả (theo tên và vị trí trong danh sách tác giả), và affiliation in cạnh tên người đó
(chỉ số trên, chú thích chân trang, khối địa chỉ) là `target_name` hoặc đơn vị trực thuộc.

Nếu cạnh liệt kê nhiều bài (`n_supporting_papers` > 1): kiểm lần lượt cho đến khi có **một** bài ủng hộ thì dừng
→ `correct`. Nếu bạn đã kiểm thêm và thấy một bài khác không ủng hộ, vẫn `correct` nhưng ghi
`note: partial – P2 không ủng hộ`.

`incorrect` khi: tác giả có in affiliation nhưng không phải `target_name` ở **mọi** bài đã kiểm (`wrong_org`); hoặc người
trên bài không phải người trong cạnh (`wrong_author`); hoặc tổ chức trong cạnh là sự gộp nhầm hai tổ chức khác nhau
(`entity_merge_error`).

Ví dụ (minh họa, không phải dòng trong mẫu):
- Đúng: cạnh "Nguyễn Văn A → Fudan University"; trên bài, tên A có chỉ số ¹ và ¹ = "School of Computer Science, Fudan
  University, Shanghai". → `correct`.
- Sai: cạnh "B → IBM (United States)"; trên bài, B chỉ ghi "IIT Bombay". → `incorrect`, `wrong_org`.
- Sai: cạnh "Wei Zhang → Tsinghua University"; trên bài có hai người tên Wei Zhang, người ở vị trí được trích dẫn ghi
  "Peking University", người kia ghi Tsinghua. → `incorrect`, `wrong_author` (xem 6.4).
- Không kiểm được: PDF không mở được và trang bài không có affiliation. → `unverifiable`, note "PDF 404".

## 3. ORG_COAUTHORED_WITH (Institution — Institution, vô hướng)

**Khẳng định của cạnh:** "Có ít nhất một bài được liệt kê, trong đó **hai tác giả khác nhau** lần lượt khai báo
`source_name` và `target_name`". Cạnh chỉ có nghĩa là hai tổ chức cùng xuất hiện qua tác giả trên một bài, **không** phải
thỏa thuận hợp tác chính thức. Hướng không quan trọng (A—B giống B—A).

`correct` khi: trên ít nhất một bài, có tác giả X in tổ chức A, có tác giả Y ≠ X in tổ chức B, và A ≠ B.

`incorrect` khi:
- Chỉ **một** tác giả mang cả hai tổ chức (một người hai affiliation) và không ai khác mang tổ chức kia → `evidence_mismatch`.
- Một trong hai tổ chức không xuất hiện trên bài → `wrong_org`.
- A và B thực ra là **cùng một** tổ chức dưới hai bản ghi (ví dụ "Microsoft (United States)" và "Microsoft Research"
  khi bài chỉ ghi "Microsoft") → `entity_merge_error` (bản ghi tổ chức bị tách/gộp sai).

**Trọng số (`n_supporting_papers`) không cần đúng chính xác.** Nhãn dựa trên sự tồn tại của ít nhất một bài ủng hộ.
Nếu bạn kiểm thêm và thấy một số bài liệt kê không ủng hộ, ghi `note: weight overstated – P3 không ủng hộ`. Không
bắt buộc kiểm hết mọi bài.

Ví dụ:
- Đúng: bài P1 có X "Fudan University", Y "Shanghai AI Laboratory"; cạnh Fudan — Shanghai AI Lab. → `correct`.
- Sai: bài P1 chỉ có tác giả Z ghi "University of Edinburgh; University of Groningen", không ai khác ghi hai tổ chức này.
  → `incorrect`, `evidence_mismatch`.

## 4. ACTIVE_IN (Institution → Topic)

**Định nghĩa "active" trong dự án:** tổ chức có **ít nhất 2 bài khác nhau** trong corpus (ACL/EMNLP + arXiv cs.CL,
2023–2025), mà trên **mỗi** bài đó (a) có ít nhất một tác giả khai báo tổ chức này và (b) bài thật sự thuộc chủ đề
`target_name`. Không có điều kiện về khoảng thời gian ngoài phạm vi 2023–2025; không yêu cầu hai bài khác năm. Cạnh
**không** đánh giá tổ chức đó có mạnh về chủ đề hay không ngoài corpus.

Định nghĩa topic dùng khi kiểm (b):
- `llm`: bài nghiên cứu/sử dụng mô hình ngôn ngữ lớn làm trọng tâm (LLM, instruction tuning, alignment).
- `mt`: dịch máy (văn bản hoặc tiếng nói), đánh giá chất lượng dịch.
- `qa`: hỏi đáp, đọc hiểu máy.
- `retrieval`: truy hồi thông tin, dense retrieval, retrieval-augmented generation (RAG).
- `summarization`: tóm tắt văn bản/hội thoại/tài liệu.
- `safety_eval`: an toàn LM, đánh giá LLM, hallucination, red teaming, jailbreak.
Một bài chỉ nhắc chủ đề thoáng qua (ví dụ một câu "có thể áp dụng cho QA") thì **không** thuộc chủ đề.

Cách kiểm: đi lần lượt các bài trong `evidence_text`; dừng khi đã có **2 bài** thỏa cả (a) và (b) → `correct`.
`incorrect` khi kiểm hết các bài mà số bài thỏa < 2:
- vì affiliation không đúng → `wrong_org`;
- vì bài không thuộc chủ đề → `evidence_mismatch` (ghi "topic" trong note);
- vì gộp nhầm tổ chức → `entity_merge_error`.
`unverifiable` khi có < 2 bài thỏa mà phần còn lại không mở được.

## 5. Danh sách error_type (chỉ điền khi `incorrect`)

| error_type | Nghĩa |
|---|---|
| `wrong_org` | Tổ chức trong cạnh không phải tổ chức tác giả khai báo trên bài. |
| `wrong_author` | Người trên bài không phải tác giả trong cạnh (nhầm vị trí, trùng tên, gán sai danh tính). |
| `entity_merge_error` | Hai thực thể khác nhau bị gộp thành một, hoặc một thực thể bị tách thành hai bản ghi (tổ chức hoặc tác giả). |
| `evidence_mismatch` | Thực thể đúng nhưng bài liệt kê không ủng hộ khẳng định (cùng một người mang cả hai tổ chức; bài không thuộc topic; không đủ 2 bài). |
| `other` | Lỗi khác; mô tả trong `note`. |

## 6. Trường hợp khó

### 6.1 Biến thể tên tổ chức
Coi là **cùng tổ chức** khi rõ ràng chỉ cùng một cơ quan: viết tắt (CMU = Carnegie Mellon University, KAIST, NTU =
Nanyang Technological University *khi ở Singapore*), tên tiếng địa phương (Technische Universität München = Technical
University of Munich; 清华大学 = Tsinghua University), tên cũ/mới (Facebook AI = Meta), có/không có quốc gia trong ngoặc
("Google (United States)" = Google). Khi viết tắt mơ hồ (NTU có thể là Nanyang hoặc National Taiwan University; UW có
thể là Washington hoặc Waterloo), dùng thành phố/quốc gia/email trên bài để quyết định; nếu bài không cho đủ thông tin →
`unverifiable`, note "viết tắt mơ hồ".

### 6.2 Lab/khoa so với trường
Đơn vị **trực thuộc** được tính là tổ chức mẹ: "Fudan NLP Lab", "School of Computer Science, Fudan University" →
**tính** là Fudan University. Ngược lại: nếu cạnh trỏ tới **đơn vị con** (ví dụ "MIT Media Lab") mà bài chỉ ghi tổ chức
mẹ ("Massachusetts Institute of Technology") → `incorrect`, `wrong_org` (cạnh khẳng định cụ thể hơn bằng chứng).
Phòng thí nghiệm **liên kết nhưng là pháp nhân riêng** (Shanghai AI Laboratory với các trường ở Thượng Hải, Vector
Institute với University of Toronto, Allen Institute for AI với University of Washington) **không** được tính là cùng
tổ chức, trừ khi bài ghi cả hai.
Công ty mẹ/con: "Google DeepMind" được tính là Google; "Microsoft Research Asia" được tính là Microsoft; "Ant Group" và
"Alibaba Group" là **hai** tổ chức khác nhau.

### 6.3 Tác giả có nhiều affiliation
Một tác giả có thể khai báo nhiều tổ chức trên cùng một bài. AFFILIATED_WITH tới **bất kỳ** tổ chức nào trong số đó đều
`correct`. Với ORG_COAUTHORED_WITH, hai tổ chức chỉ do **một** người mang (và không ai khác mang tổ chức kia) →
`incorrect`, `evidence_mismatch` (xem mục 3).

### 6.4 Trùng tên tác giả
Xác định người bằng **vị trí trong danh sách tác giả** (ghi trong `evidence_text`, ví dụ "vị trí 3") cùng với tên. Nếu
trên bài có hai người trùng tên, dùng vị trí. Nếu `source_name` không xuất hiện trên bài ở vị trí đó (tên khác hẳn) →
`incorrect`, `wrong_author`. Khác biệt chính tả/dấu/thứ tự họ tên ("Arık" vs "Arik", "Liu Yang" vs "Yang Liu") không tính
là sai. Với AFFILIATED_WITH nhiều bài: nếu trên các bài khác nhau tên giống nhau nhưng rõ ràng là **hai người** (lĩnh vực,
tổ chức, email khác hẳn), ghi `entity_merge_error` nếu vì thế khẳng định của cạnh sai; nếu cạnh vẫn đúng trên một bài thì
`correct` + note.

### 6.5 Bài không in affiliation
Một số bài arXiv không ghi affiliation trên trang abstract nhưng PDF có. Luôn mở PDF. Nếu PDF cũng không có (hiếm) →
`unverifiable`, note "no affiliation in PDF". **Không** dùng hồ sơ cá nhân, LinkedIn hay trang Google Scholar để kiểm.

### 6.6 Bài bị rút/đổi phiên bản
Dùng phiên bản ở `pdf_url`. Nếu arXiv có nhiều phiên bản và affiliation khác nhau giữa các phiên bản, chấp nhận nếu
**bất kỳ** phiên bản nào ủng hộ, ghi note.

## 7. Hai người chấm và dòng is_overlap

- Có 30 dòng `is_overlap=1` (10 mỗi loại cạnh) trong `review_sheet_round1.csv`.
- **Một người chấm:** chấm toàn bộ tệp chính; bỏ qua tệp `..._overlap_reviewer2.csv`. Script sẽ báo không tính được
  kappa.
- **Hai người chấm:** người 1 (và/hoặc người 2) chia nhau chấm tệp chính (mỗi dòng ghi đúng tên người chấm); người 2
  chấm 30 dòng trong `review_sheet_round1_overlap_reviewer2.csv` **mà không xem** tệp chính. Người chấm dòng overlap trong
  tệp chính phải khác người chấm tệp overlap. Sau khi cả hai xong, nếu một dòng overlap bất đồng nhãn, hai người thảo luận
  và điền `adjudicated_label` (và `error_type` tương ứng nếu `incorrect`) trong **tệp chính**. Kappa được tính trên nhãn
  **trước** khi thống nhất.

## 8. Lưu tệp

Mở bằng Excel được (tệp có BOM UTF-8). Khi lưu, chọn **"CSV UTF-8 (Comma delimited)"**. Không đổi tên cột, không xóa
hoặc thêm dòng, không đổi thứ tự cột. Script chấp nhận dấu phân cách `,` hoặc `;` (Excel một số vùng dùng `;`).
Sau đó chạy:

```
uv run python evaluation/compute_precision.py --round 1
```
