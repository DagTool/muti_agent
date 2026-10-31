# Test strategy và performance plan W2 — bản nháp

**Mục đích:** dùng bằng chứng có thể lặp lại cho Gate W2 và các gate triển khai sau này. Chưa coi CI xanh là nghiệm thu sản phẩm.

## Các lớp kiểm tra

| Lớp | Điều kiện chạy | Hành vi cần chứng minh | Bằng chứng |
|---|---|---|---|
| Unit/API | Mỗi PR | RBAC, workspace scope, state transition, idempotency, schema/path validation | Pytest và regression case cụ thể |
| Migration | Mỗi PR đổi schema, CI | DB trống upgrade/check/downgrade; constraint giữ dữ liệu đúng | `scripts.check_fresh_migration`, log CI |
| Frontend | Mỗi PR UI | TypeScript build, loading/error/empty state, quyền hiển thị | `npm run build`, E2E sau khi có harness |
| Kafka integration | Mỗi PR thay event/worker | Outbox publish, duplicate delivery, crash giữa publish/mark, rebalance, DLQ | Test với PostgreSQL/Kafka thật, event ID và audit |
| Sandbox/security | Mỗi PR thay file/tool/runner | Path traversal, symlink, secret, network, resource limit, untrusted code | Test sandbox + review threat model |
| Workflow/UAT | Gate W5 trở đi | Hai demo API và full-stack theo acceptance scenarios, approval, PR/CI/review | Kịch bản, artifacts, Git SHA và người duyệt |
| Recovery/operations | Trước staging | Worker chết ở claim, model call, DB commit; backup/restore; replay | Runbook, audit/trace, restore log |

CI hiện chạy Python tests, Ruff, migration check và frontend build. Local `pytest` dùng SQLite nên không chứng minh hành vi PostgreSQL locking/Kafka. `smoke_ai_execution` dùng output mẫu, không gọi OpenAI; luồng model thật cần API key và ngân sách được owner cấp. Không dùng production data cho test.

## Các case rủi ro cao cần bổ sung

1. **Workspace/RBAC:** owner/member/viewer, token hết hạn/thu hồi, ID khác workspace cho mọi read/mutation route và SSE; trả 404 khi không thấy tài nguyên.
2. **Event delivery:** gửi cùng event 2 lần; gửi cùng attempt với event ID khác; event attempt cũ sau attempt mới; crash publisher sau Kafka ack; worker crash trước/sau DB commit.
3. **Retry/cancel:** recovery task running quá hạn, giới hạn ba attempt, cancel khi model đang chạy, không có artifact/approval trái state, side effect cũ không ghi đè.
4. **Output an toàn:** prompt injection, path traversal/symlink, secret phổ biến và biến thể, quá giới hạn file, code test cố truy cập mạng hoặc host path.
5. **Budget/approval:** hai task cạnh tranh budget, usage thiếu, replay approval, người không đủ role, deploy/staging không qua gate.

Mỗi case lưu input, expected state, actual state, task/run/event ID và commit SHA. Test không chỉ xác nhận HTTP status; cần kiểm tra DB, outbox, audit và side effect thực tế khi phù hợp.

## Đo hiệu năng

| Chỉ số | Cách đo | Mốc quyết định ban đầu |
|---|---|---|
| API latency p50/p95/p99 | 100 request đồng thời cho create/list/get, tách warm-up, ghi DB size | Lấy baseline W3; chưa đặt SLA khi chưa có staging |
| Task queue wait | `task.created` → worker claim theo correlation ID | Báo median/p95 và outbox/Kafka lag |
| End-to-end task | Request → terminal task/approval, tách model latency và QA | Báo median/p95 theo mode/role/demo |
| Recovery time | Kill worker tại từng điểm, đo tới task ready/terminal | Bằng chứng không mất task, không side effect lặp |
| Resource/cost | CPU/RAM runner, Kafka lag, token/call, chi phí ước tính | Báo theo workload và model, không suy diễn từ mock |

Chạy cùng workload ít nhất ba lần, ghi môi trường (CPU/RAM, DB/Kafka config, model/version), số mẫu, thời điểm, commit SHA và các percentile. Tách lỗi khỏi mẫu latency; ghi throughput và error rate. Không đặt ngưỡng release khi chưa có baseline và budget owner xác nhận.

## Gate W2

Reviewer theo một `run_id` cụ thể từ API → task/outbox → Kafka/dispatcher → worker → DB/result/artifact/audit; xác nhận PostgreSQL là nguồn business state. Dùng [architecture](../architecture/architecture.md), [event contracts](../architecture/event-contracts.md) và [threat model](../architecture/threat-model.md). Các kiểm thử Kafka crash/rebalance, sandbox hardening và hai demo vẫn là việc của các gate sau; phải ghi rõ khi chưa có evidence.
