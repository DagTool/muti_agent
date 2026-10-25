# ADR-001: Monorepo và state ownership

**Trạng thái:** Accepted cho prototype, 25/10/2026.

Giữ API, event contracts và workers trong cùng một repository để thay đổi schema và hành vi có thể được review cùng lúc. PostgreSQL là nguồn sự thật cho project/task/audit. Kafka vận chuyển commands/results theo at-least-once delivery; trạng thái task không được suy ra chỉ từ Kafka offset.

Worker có thể được tách thành deployment riêng khi có số liệu tải. Hiện tại mỗi process chạy từ cùng package Python. Không tạo một database riêng cho mỗi agent.
