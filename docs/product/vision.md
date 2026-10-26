# AgentForge AI — Vision v0.2 (dự thảo, 26/10/2026)

## Vấn đề

Một yêu cầu phần mềm thường bị tách thành nhiều cuộc trao đổi, nhánh mã và lần kiểm thử. Người giao việc khó biết quyết định nào đã được duyệt, mã nào đã được chạy, lỗi nào còn mở và chi phí AI đã dùng. AgentForge AI gom yêu cầu, quyết định, tác vụ, kết quả và bằng chứng kiểm thử vào một workflow có thể truy vết.

## Người dùng và hành trình

- **Chủ dự án:** mô tả mục tiêu, duyệt phạm vi và điểm bàn giao, xem tiến độ, ngân sách và kết quả.
- **Người phát triển/reviewer:** đọc tiêu chí chấp nhận, xem diff/PR, kiểm tra test và quyết định có nhận thay đổi hay không.
- **Người vận hành:** theo dõi hàng đợi, xử lý task lỗi hoặc treo, kiểm tra audit và khôi phục sau sự cố.

Hành trình chuẩn: tạo project và gắn repository → PM đề xuất PRD → chủ dự án duyệt scope → Architect đề xuất thiết kế → các agent triển khai theo dependency → QA kiểm tra trong sandbox → mở PR kèm báo cáo → chủ dự án duyệt staging/bàn giao. Một bước bị từ chối hoặc lỗi phải hiện rõ lý do và đường quay lại.

## Nguyên tắc sản phẩm

1. PostgreSQL giữ trạng thái nghiệp vụ; Kafka chuyển công việc và có thể giao lặp. Mọi tác động nghiệp vụ cần idempotent.
2. Agent chỉ dùng tool và quyền được cấp. Chạy mã sinh ra trong sandbox; không tự triển khai production.
3. Có người duyệt scope, thay đổi nhạy cảm, staging và bàn giao. Agent không tự nâng ngân sách.
4. Mỗi kết quả có nguồn gốc: yêu cầu, task, agent, phiên bản model/prompt, artifacts, test, PR và audit.
5. Khi lỗi, hủy hoặc hết ngân sách, hệ thống dừng an toàn và giải thích được trạng thái.

## Phạm vi và cách đo

Phạm vi v1.0, phần hoãn lại và KPI dự kiến nằm trong [PRD](prd-v1.md). Hai dự án demo và 20 kịch bản chấp nhận là tiêu chí thử nghiệm; các KPI trong kế hoạch gốc chưa phải kết quả đã đo. Bản chạy hiện tại là prototype local với workflow mock và chế độ OpenAI tùy chọn; [README](../../README.md) ghi rõ những phần đã có và còn thiếu.

**Quyết định cần chủ dự án xác nhận cho Gate W1:** người phê duyệt cuối, hai bài toán demo, giới hạn ngân sách mặc định và phạm vi repository được phép chỉnh sửa.
