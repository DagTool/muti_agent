# Công việc còn lại theo kế hoạch 16 tuần

1. Hoàn tất PRD/use cases và review phạm vi với chủ dự án. Tạo GitHub repo, board và branch protection khi có repository đích.
2. User/membership/token RBAC local đã có migration và kiểm thử role. Cần OIDC/JWT, invitation, token rotation, quản lý thành viên trên UI và kiểm thử multi-workspace đầy đủ.
3. Bổ sung task state machine và DAG tổng quát. Recovery worker hiện dựa vào `updated_at` 10 phút và giới hạn 3 lần thử; cần lease/heartbeat chính thức, backoff và kiểm thử crash/rebalance.
4. Nối LangGraph checkpoint vào run thực tế. Chế độ OpenAI đã có PM/Architect/Developer/QA theo chuỗi và schema file sinh, nhưng chưa có model router đa nhà cung cấp hoặc đánh giá chất lượng tự động.
5. Docker sandbox đã chạy `compileall`/`unittest` trong local; project sinh được lưu thành Git repository/commit riêng và có kiểm tra một số định dạng secret phổ biến. Cần secret scanner đầy đủ, hardening cho multi-tenant, worktree của repository người dùng, PR qua CI/review và staging approval.
6. Dashboard đã có audit timeline, token usage và stream SSE theo project để tự làm mới khi audit thay đổi. Cần conversation/messages, WebSocket gateway nếu có nhu cầu hai chiều, và cost report theo đơn giá model thực tế.
7. Kiểm thử Kafka crash/rebalance, staging, backup/restore, bảo mật, benchmark và hai demo nghiệm thu.

Không đánh dấu các gate tuần là hoàn thành trước khi kiểm thử theo điều kiện trong tài liệu gốc.
