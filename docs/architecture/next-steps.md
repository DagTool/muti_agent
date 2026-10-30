# Công việc còn lại theo kế hoạch 16 tuần

1. Dự thảo W1 đã có [PRD](../product/prd-v1.md), [12 use cases và 20 acceptance scenarios](../product/use-cases.md), [backlog](../product/backlog.md), [risk register](../product/risk-register.md), issue/PR templates và [quy ước đóng góp](../../CONTRIBUTING.md). Cần chủ dự án duyệt Gate W1, xác nhận hai demo và người phụ trách; GitHub board, labels và branch protection vẫn chưa cấu hình.
2. User/membership/token RBAC local đã có migration, kiểm thử role, cấp token thay thế, thu hồi và quản lý thành viên cơ bản trên UI. Cần OIDC/JWT, invitation, kiểm thử multi-workspace đầy đủ và chính sách vòng đời token khi chạy production.
3. Bổ sung task state machine và DAG tổng quát. Recovery worker hiện dựa vào `updated_at` 10 phút và giới hạn 3 lần thử; cần lease/heartbeat chính thức, backoff và kiểm thử crash/rebalance.
4. Nối LangGraph checkpoint vào run thực tế. Chế độ OpenAI đã có PM/Architect/Developer/QA theo chuỗi và schema file sinh, nhưng chưa có model router đa nhà cung cấp hoặc đánh giá chất lượng tự động.
5. Docker sandbox đã chạy `compileall`/`unittest` trong local; project sinh được lưu thành Git repository/commit riêng và có kiểm tra một số định dạng secret phổ biến. Cần secret scanner đầy đủ, hardening cho multi-tenant, worktree của repository người dùng, PR qua CI/review và staging approval.
6. Dashboard đã có audit timeline, token usage và stream SSE theo project để tự làm mới khi audit thay đổi. Cần conversation/messages, WebSocket gateway nếu có nhu cầu hai chiều, và cost report theo đơn giá model thực tế.
7. Kiểm thử Kafka crash/rebalance, staging, backup/restore, bảo mật, benchmark và hai demo nghiệm thu.

Không đánh dấu các gate tuần là hoàn thành trước khi kiểm thử theo điều kiện trong tài liệu gốc.
