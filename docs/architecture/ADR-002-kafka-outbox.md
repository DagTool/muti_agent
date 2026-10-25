# ADR-002: Kafka và transactional outbox

**Trạng thái:** Accepted cho prototype, 25/10/2026.

API ghi task và outbox event trong cùng DB transaction. Publisher gửi tới Kafka rồi ghi `published_at`. Sự cố giữa hai bước có thể gửi trùng, vì vậy worker khóa task và lưu `(consumer_name, event_id)` trong cùng transaction với thay đổi nghiệp vụ. Consumer chỉ commit offset sau khi xử lý thành công.

Dispatcher dùng `agentforge.task.commands.v1` và chuyển role `developer` đến `agentforge.tasks.developer.v1`. Role/event không được hỗ trợ đi DLQ. Worker mẫu chưa gọi tool bên ngoài; khi thêm Git/sandbox phải dùng `execution_id` để nhận diện side effect đã xảy ra.

Local Kafka KRaft một node chỉ dành cho phát triển. Staging/production cần TLS/SASL, ACL, replication, retention và restore plan.
