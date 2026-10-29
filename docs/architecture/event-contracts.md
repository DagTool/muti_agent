# Event contracts W2 — bản để duyệt

**Trạng thái:** Draft cho prototype hiện tại. Nguồn định nghĩa thực thi: `packages/communication/contracts.py`.

## Envelope v1

`EventEnvelope` là JSON, từ chối field thừa và chỉ nhận `schema_version = 1`. `event_type` hiện có `task.execute.requested` và `task.execute.completed`. Envelope sau khi serialize có `event_id`, `occurred_at`, `correlation_id`, `workspace_id`, `project_id`, `task_id`, `execution_id`, `idempotency_key`, `sender`, `recipient_role`, `attempt` (1–3), `payload`; `causation_id` có thể null. Model tự sinh `event_id`, `occurred_at` nếu producer không cấp.

| Field | Ý nghĩa và invariant |
|---|---|
| `event_id` | UUID cho delivery logic; consumer lưu `(consumer_name, event_id)` |
| `correlation_id` | UUID xuyên các event của một task; audit dùng cùng giá trị |
| `causation_id` | ID command tạo ra result, nếu có |
| `execution_id` | UUID của lần thực thi; cần dùng để fence side effect trong tương lai |
| `workspace_id`, `project_id`, `task_id` | Consumer đối chiếu DB trước khi xử lý |
| `idempotency_key` | Hiện có dạng `<task_id>:attempt-<n>`; không thay thế `event_id` |
| `attempt` | Phải bằng attempt đang lưu trên task; tối đa 3 |
| `payload` | Command chứa `instructions`, `acceptance_criteria`, `mode`; result chứa `result` |

## Các topic đang chạy

| Topic | Producer → Consumer | Key |
|---|---|---|
| `agentforge.task.commands.v1` | API/worker outbox → dispatcher | task ID |
| `agentforge.tasks.developer.v1`, `.qa.v1` | dispatcher → mock workers | task ID |
| `agentforge.tasks.pm.v1`, `.architect.v1`, `.openai.developer.v1`, `.openai.qa.v1` | dispatcher → OpenAI workers | task ID |
| `agentforge.task.results.v1` | worker outbox → chưa có result ingestor | task ID |
| `agentforge.task.dlq.v1` | dispatcher/worker → operator (chưa có tooling replay) | task ID hoặc `invalid-schema` |

`task.results.v1` hiện là event log; task state được worker ghi thẳng vào PostgreSQL trong cùng transaction với result outbox. Không giả định có consumer xử lý result để đổi trạng thái. Ordering chỉ bảo đảm trong một partition khi cùng task ID làm key.

## Delivery, versioning và các lỗ hổng

Outbox publisher giữ row lock khi publish và chỉ đánh dấu `published_at` sau khi Kafka xác nhận. Crash giữa hai bước sẽ phát lại. Dispatcher có thể route lại trước khi commit offset. Worker phải kiểm tra event ID, task status, attempt và workspace trong transaction. Event không hợp lệ/role không hỗ trợ đi DLQ; lỗi xử lý tạm thời giữ offset chưa commit để retry.

Thay đổi field mang nghĩa khác hoặc payload không tương thích cần schema version/topic mới, producer và consumer chạy song song trong giai đoạn chuyển tiếp, cùng test cho cả hai version. Prototype hiện chỉ nhận v1; chưa có registry, migration contract hay compatibility suite. Cần định nghĩa cấu trúc DLQ, giới hạn retry và cách replay thủ công trước production. Không đưa secret, raw prompt hoặc dữ liệu cá nhân vào event/log.
