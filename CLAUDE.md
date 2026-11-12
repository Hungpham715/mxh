# CLAUDE.md

Hướng dẫn dành cho Claude Code / Codex / Cline / Cursor / OpenCode khi làm việc trong repository này.

## Tổng quan project

GraphRAG — project đang ở giai đoạn khởi đầu, chưa có code. Khi code đã hình thành, cập nhật lại file này (cấu trúc thư mục, lệnh build/test/run, convention thực tế).

## Nguyên tắc viết code — luôn áp dụng `coding-simple`

Skill **`coding-simple`** (`.claude/skills/coding-simple/SKILL.md`) là chuẩn mặc định cho **mọi** công việc liên quan đến code trong project này: viết code mới, refactor, review, sửa bug, viết test.

Luôn load và tuân theo skill này. Những điểm cốt lõi cần nhớ kể cả khi chưa load:

- **Ưu tiên: code rõ ràng > code ngắn > code khéo léo.** Mục tiêu không phải ít dòng code hơn.
- Viết code để một engineer mới vào team hiểu nhanh: control flow tường minh, guard clause, tên biến mô tả rõ, intermediate variable khi nó làm lộ các bước quan trọng.
- Tránh mặc định: nested ternary, one-liner nén, comprehension phức tạp, abstraction sớm, metaprogramming không lý do.
- **Giữ nguyên hành vi khi refactor** — input, output, side effect, error behavior, thứ tự thực thi. Không chắc thì không âm thầm đổi.
- **Phân loại mọi pattern quan trọng** khi đưa ra: industry-standard / big-tech-style / framework convention / project convention / custom choice. Không gắn nhãn "best practice" cho custom choice.
- Production quality không đồng nghĩa phức tạp tối đa: chọn architecture đơn giản nhất đáp ứng yêu cầu thật. Nhưng **không bao giờ** đơn giản hóa bỏ security, validation, transaction boundary, error handling cần thiết.
- Code "boring" là code production tốt. Chỉ sửa trong phạm vi task được yêu cầu.

## Frontend — chọn skill phù hợp theo task

Ngoài `coding-simple` (vẫn áp dụng cho phần code), với công việc frontend/UI thì chọn skill theo bảng sau:

| Tình huống | Skill dùng |
|---|---|
| Cần định hướng thẩm mỹ: thiết kế giao diện có bản sắc riêng, chọn palette, typography, layout, tránh giao diện trông "template" | `frontend-design` |
| Cần dữ liệu UI/UX để tra cứu: style theo loại sản phẩm, color palette, font pairing, UX guidelines (accessibility, touch, form...), hướng dẫn theo stack cụ thể (react, nextjs, vue, html-tailwind...) | `ui-ux-pro-max` |
| Cần xây artifact web phức tạp cho claude.ai: nhiều component, state management, routing, React + Tailwind + shadcn/ui đóng gói thành 1 file HTML | `web-artifacts-builder` |

Gợi ý phối hợp khi làm một giao diện hoàn chỉnh:

1. `ui-ux-pro-max` → chạy `--design-system` để lấy style/color/typography phù hợp sản phẩm, và tra UX guidelines (accessibility, responsive...) bằng `search.py --domain <domain>`.
2. `frontend-design` → tinh chỉnh quyết định thẩm mỹ để giao diện có điểm nhấn riêng, không rập khuôn.
3. `coding-simple` → áp dụng khi viết code component (đặc biệt mục React/TypeScript: không nested ternary, không memoization/context/global state khi chưa có vấn đề thật).
4. Artifact đơn giản 1 file HTML/JSX thì **không** cần `web-artifacts-builder` — skill đó chỉ dành cho artifact phức tạp nhiều component.

## Quy ước chung

- Skills nằm trong `.claude/skills/` — gọi bằng tên (ví dụ `/coding-simple`) hoặc tự load qua Skill tool khi task trùng khớp.
- Không bịa convention của project khi chưa có code; khi thêm code đầu tiên, thiết lập convention rõ ràng rồi ghi lại vào file này.
