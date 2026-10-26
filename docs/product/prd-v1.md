# AgentForge AI — PRD v0.1

**Trạng thái:** Dự thảo để chủ dự án duyệt Gate W1, 26/10/2026. Tài liệu mô tả mục tiêu v1.0, không khẳng định đã triển khai.

## Mục tiêu

Biến một yêu cầu phần mềm thành PR có kiểm thử và bằng chứng bàn giao qua workflow nhiều agent, với trạng thái bền vững, quyền hạn rõ, giới hạn ngân sách và các điểm duyệt của con người.

## Phạm vi MVP

1. Owner/member/viewer trong workspace; chỉ người có quyền mới tạo run, duyệt hoặc quản trị token.
2. Project có yêu cầu phiên bản hóa, repository đích và ngân sách.
3. PM sinh PRD/backlog; Architect sinh thiết kế/contract; Developer chỉnh mã trong branch/worktree; QA chạy kiểm tra trong sandbox. Kết quả của từng agent có schema và artifact.
4. Orchestrator điều phối task theo dependency, không chạy task khi prerequisite chưa xong; retry có giới hạn, hủy và khôi phục được.
5. Outbox và Kafka vận chuyển lệnh at-least-once; duplicate/replay không nhân đôi tác động nghiệp vụ.
6. Dashboard cho xem tiến độ, thông điệp agent, logs, test, artifacts, PR, token/chi phí và hàng đợi approval.
7. PR được mở sau kiểm tra; staging và bàn giao chỉ theo phê duyệt có audit.

## Ngoài phạm vi v1.0

Tự deploy production, chạy mã không tin cậy trên host hoặc sandbox dùng chung không giới hạn, billing thương mại, marketplace agent, tự tăng ngân sách hay tự merge thay chủ dự án. Không hứa mã AI sinh luôn đúng.

## Luồng chính

1. Chủ dự án tạo project và yêu cầu, chọn repository/phạm vi thư mục và ngân sách.
2. PM đề xuất scope. Chủ dự án duyệt hoặc yêu cầu sửa; mọi quyết định có audit.
3. Architect tạo thiết kế và task DAG; vòng phụ thuộc bị từ chối.
4. Agent phát triển làm việc trong nhánh/worktree riêng. QA chạy test trong sandbox, ghi kết quả và phản hồi sửa tối đa ba vòng.
5. Khi các gate đạt, hệ thống tạo PR và change report. Chủ dự án quyết định staging/bàn giao.
6. Run lỗi, bị hủy hoặc gián đoạn có thể xem nguyên nhân, retry có giới hạn và tiếp tục từ trạng thái bền vững.

## Điều kiện chấp nhận v1.0

- Hai [dự án demo](use-cases.md#hai-dự-án-demo-đề-xuất) hoàn tất với PR, test, hướng dẫn chạy và xác nhận của người dùng.
- 20 [kịch bản chấp nhận](use-cases.md#20-kịch-bản-chấp-nhận) cho kết quả mong đợi hoặc báo lỗi minh bạch; mục tiêu kế hoạch gốc là ít nhất 95%.
- Task có owner, trạng thái, timestamps, attempt, correlation ID; duplicate Kafka không nhân đôi commit/approval/audit.
- Không có secret trong log/artifact/PR; mã sinh không chạy với quyền host; quyền workspace được kiểm tra xuyên suốt.
- CI platform xanh; không còn defect blocker/critical; khôi phục sau crash/restart có bằng chứng.
- Có báo cáo token và ước tính chi phí theo project; vượt ngân sách chặn phát việc mới hoặc xin duyệt.

## Giả định và câu hỏi mở

- Một owner cho mỗi workspace ở MVP; quyền cộng tác mở rộng sau khi có OIDC/invitation.
- Repository đích do chủ dự án cấp quyền scoped; hệ thống không tự chọn repository hay tự merge.
- Giá model và hạn mức thực tế có thể thay đổi; chi phí là ước tính, cần chốt provider/model và nguồn giá khi triển khai.
- Cần chốt người duyệt Gate W1, bài toán demo, repository đích, giới hạn ngân sách và chính sách dữ liệu gửi đến model trước khi nghiệm thu.

## Liên kết thực thi

[Use cases và acceptance](use-cases.md) · [Backlog](backlog.md) · [Risk register](risk-register.md) · [Kế hoạch gốc](../../AgentForge_AI_Ke_Hoach_Phat_Trien_Chi_Tiet.md)
