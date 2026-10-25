# Vision v0.1

AgentForge AI giúp một người đưa yêu cầu phần mềm vào một workflow có thể theo dõi: từ project và backlog đến code, kiểm thử và bàn giao. Mỗi tác vụ phải có trạng thái bền vững, nguồn gốc, giới hạn quyền và điểm phê duyệt khi có rủi ro.

## Người dùng đầu tiên

- **Chủ dự án:** mô tả nhu cầu, duyệt phạm vi, xem tiến độ và kết quả.
- **Người phát triển/reviewer:** kiểm tra PR, test evidence, logs và lỗi.
- **Người vận hành:** xử lý backlog, retry, DLQ và sự cố.

## Giới hạn của checkout hiện tại

Checkout này là lát cắt nền tảng cho giai đoạn khởi động, **chưa có agent dùng LLM hoặc chạy code**. Worker chỉ trả kết quả giả. Các luồng approval, sandbox, Git PR, dashboard, auth người dùng và RBAC đầy đủ chưa triển khai.

## Demo đầu tiên

Tạo project và task developer; API ghi task và event vào PostgreSQL cùng giao dịch; outbox publisher gửi Kafka; dispatcher định tuyến theo role; worker mẫu cập nhật task, lưu audit và result event. Gửi lại cùng event không tạo lần hoàn thành thứ hai.
