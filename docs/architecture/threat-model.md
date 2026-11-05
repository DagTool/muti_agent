# Threat model W2 — bản nháp

**Phạm vi:** prototype `main` ngày 31/10/2026; API, PostgreSQL, Kafka, OpenAI worker, Git artifact local, Docker sandbox và dashboard. Đây là phân tích thiết kế, chưa phải kết quả pentest hoặc chứng nhận môi trường production.

## Tài sản và ranh giới tin cậy

- **Tài sản:** API bootstrap key và member tokens; nội dung requirement/PRD/code; trạng thái task/run/approval; audit trail; token budget; artifact và Git commit sinh; dữ liệu gửi tới model.
- **Người dùng → API:** header `X-API-Key`, body và idempotency key là input không tin cậy. API là điểm kiểm soát role và workspace.
- **API/worker → PostgreSQL:** DB là nguồn business state; chỉ transaction được phép quyết định transition. Kafka là vận chuyển at-least-once.
- **Kafka → worker:** envelope phải được validate và đối chiếu task/project/workspace/attempt trong DB. Event trùng, cũ hoặc sai schema có thể đến sau khi state thay đổi.
- **Worker → provider / filesystem / Docker:** model output và code sinh không tin cậy. Side effect bên ngoài DB không rollback cùng transaction; Docker socket trên host là quyền nhạy cảm.
- **Dashboard → browser:** API key nằm trong bộ nhớ tab; XSS vẫn có thể đọc dữ liệu đang hiển thị và gửi request với quyền người dùng.

## Các kịch bản ưu tiên

| ID | Kịch bản | Tác động | Kiểm soát hiện có | Việc còn thiếu / bằng chứng cần có |
|---|---|---|---|---|
| T01 | Token bị lộ hoặc dùng sau thu hồi | Đọc/ghi nhầm workspace | Token lưu dạng hash, hết hạn 30 ngày, revoke, RBAC API | OIDC, vòng đời/rotation production, log không lộ key, test cross-workspace |
| T02 | ID của project/run/approval khác workspace được đoán | Rò dữ liệu hoặc phê duyệt trái phép | Route chính lọc workspace; test approval/activity và 17 route tài nguyên + SSE với ID khác workspace | Kiểm thử trong triển khai nhiều tenant và rà soát route mới khi bổ sung API |
| T03 | Prompt injection trong requirement/repo/model output | Agent sửa file ngoài scope hoặc lộ secret | Output schema, kiểm tra path, chỉ QA chạy code trong sandbox | Allowlist tool/repo, chính sách dữ liệu gửi model, adversarial tests |
| T04 | Code sinh thoát sandbox hoặc dùng Docker socket | Chiếm host, đọc secret, truy cập mạng | Container QA không mạng, giới hạn tài nguyên | Hardening runner cho tenant không tin cậy, test mount/symlink/network |
| T05 | Event trùng hoặc worker cũ ghi sau retry | Sai state, artifact/Git lặp, chặn run sai | Outbox, processed-event, task lock/attempt; fix attempt cũ | Lease/heartbeat/fencing cho cả side effect, crash/rebalance tests |
| T06 | Secret trong code/artifact/log/PR | Lộ credential | Chặn một số định dạng secret phổ biến trước ghi file | Scanner đầy đủ, redaction, review và test false negative |
| T07 | Approval bị bỏ qua khi chạy/deploy | Thay đổi ngoài ý muốn | Scope/handover approval local; deploy production chưa có | Approval matrix và enforcement cho GitHub PR, staging, deploy, xóa dữ liệu |
| T08 | Budget race hoặc model call không có usage | Chi phí vượt giới hạn | Token budget mềm và usage theo task | Reservation/limit cứng, alert và cost report theo giá thật |

## Ma trận quyền và phê duyệt

| Hành động | Viewer | Member | Owner | Gate mục tiêu |
|---|---|---|---|---|
| Xem project, task, artifact trong workspace | Có | Có | Có | Workspace scope |
| Tạo project/requirement/run/task, hủy hoặc resume run | Không | Có | Có | Idempotency và audit |
| Điều chỉnh budget, quản lý member/token | Không | Không | Có | Owner API |
| Duyệt scope/handover | Không | Không | Có | Approval record + audit |
| Tạo PR vào repo người dùng, staging, deploy production | Chưa triển khai | Chưa triển khai | Chưa triển khai | Review và human approval bắt buộc |

## Quy tắc thiết kế cần chốt

1. Token và model secret chỉ cấp cho process cần dùng; không đưa vào prompt, event, artifact, log hoặc Git. Tách bootstrap key local khỏi cơ chế production.
2. Mọi route theo ID phải chứng minh workspace scope trước khi trả dữ liệu hoặc side effect. Worker xác minh quan hệ `task → project → workspace` với DB, không tin ID trong event.
3. Attempt mới cấp fencing token/lease bền vững; hoàn tất task và ghi artifact chỉ khi token vẫn hợp lệ. Với file/Git, dùng workspace riêng mỗi attempt hoặc atomic publish để worker cũ không ghi đè.
4. Mã sinh và test chạy trong runner cô lập, filesystem allowlist, không mạng mặc định, không mount host Docker socket cho job không tin cậy.
5. Phê duyệt được lưu cùng run/state transition và audit; không suy ra approval từ text chat hay chỉ từ giao diện.

**Điều kiện duyệt:** reviewer xác nhận owner của từng ranh giới, mức rủi ro còn lại và test evidence trong [test strategy](../testing/test-strategy.md). Không tuyên bố T01–T08 đã được giải quyết chỉ vì đã liệt kê.
