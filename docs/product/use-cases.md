# Use cases và acceptance — dự thảo W1

## 12 use cases

| ID | Vai trò | Mục đích | Kết quả mong đợi |
|---|---|---|---|
| UC01 | Owner | Tạo workspace/project | Project và audit được lưu |
| UC02 | Owner/member | Lưu phiên bản yêu cầu | Run dùng đúng phiên bản đã chọn |
| UC03 | Owner | Gắn repository/phạm vi sửa | Agent chỉ sửa đúng repo/phạm vi |
| UC04 | PM agent | Đề xuất PRD/backlog | Scope có artifact và chờ duyệt |
| UC05 | Owner | Duyệt/từ chối scope | Quyết định có lý do, audit và chuyển trạng thái đúng |
| UC06 | Architect agent | Tạo thiết kế và task DAG | Contract và dependency hợp lệ |
| UC07 | Developer agent | Viết mã trên branch riêng | Có diff/commit gắn task |
| UC08 | QA agent | Chạy test trong sandbox | Có log, kết quả và defect |
| UC09 | Owner/member | Theo dõi tiến độ | Thấy task, messages, audit, artifacts |
| UC10 | Owner | Duyệt PR/staging/bàn giao | Chỉ hành động được sau gate và có audit |
| UC11 | Operator | Retry/khôi phục task lỗi | Không nhân đôi tác động, có giới hạn attempt |
| UC12 | Owner | Xem token/chi phí và chỉnh budget | Có số liệu theo project, vượt cap bị chặn |

## 20 kịch bản chấp nhận

Mỗi AC cần được chạy trên môi trường phù hợp và lưu bằng chứng trước khi đánh dấu đạt; danh sách này chưa phải kết quả kiểm thử.

1. **AC01:** Owner tạo project hợp lệ; API trả ID, project hiện trên dashboard và có audit.
2. **AC02:** Cùng idempotency key gửi tạo project hai lần; chỉ có một project.
3. **AC03:** Member lưu yêu cầu phiên bản 2; run cũ vẫn tham chiếu phiên bản 1.
4. **AC04:** Viewer thử tạo run; bị từ chối và không có task/outbox mới.
5. **AC05:** PM hoàn thành PRD hợp schema; run chờ approval scope.
6. **AC06:** Owner từ chối scope kèm lý do; task triển khai không được phát.
7. **AC07:** Owner duyệt scope; thiết kế/triển khai chỉ bắt đầu một lần dù lệnh duyệt gửi lặp.
8. **AC08:** Architect tạo DAG có vòng; API/orchestrator từ chối và nêu cycle.
9. **AC09:** Task có dependency chưa xong không được claim.
10. **AC10:** Hai agent được giao file trùng; hệ thống tránh ghi đè hoặc chặn xung đột.
11. **AC11:** Developer tạo diff ngoài allowlist hoặc thoát workspace bằng symlink; bị chặn.
12. **AC12:** File sinh chứa secret mẫu; không xuất hiện trong commit, log hoặc artifact công khai.
13. **AC13:** QA thất bại; defect và log gắn đúng task, run không được bàn giao.
14. **AC14:** QA → Developer sửa → QA kiểm lại; sau ba vòng thất bại run bị chặn.
15. **AC15:** Event Kafka được giao lặp; task chỉ có một tác động hoàn thành và một audit tương ứng.
16. **AC16:** Worker chết khi đang chạy; task được khôi phục/retry có giới hạn, không hoàn thành giả.
17. **AC17:** Owner hủy run; không phát task mới và trạng thái cuối được giữ sau restart.
18. **AC18:** Dùng hết budget; lệnh model mới bị chặn hoặc chờ phê duyệt, không tự tăng cap.
19. **AC19:** PR chỉ mở sau test/gate yêu cầu; PR chứa diff, test summary và giới hạn đã biết.
20. **AC20:** Staging/bàn giao cần owner duyệt; người xem khác không thể duyệt, mọi quyết định có audit.

## Hai dự án demo đề xuất

**D1 — Task API Python:** từ mô tả nghiệp vụ tạo REST API CRUD đơn giản, migration, unit/integration tests, README chạy local và PR. Bài demo kiểm tra backend, database, QA và Git handoff.

**D2 — Dashboard task React:** từ API contract có sẵn tạo trang danh sách/chi tiết task với loading/error/empty states, accessibility cơ bản, component tests và PR. Bài demo kiểm tra frontend, contract, QA và trải nghiệm phê duyệt.

Hai bài demo cần chủ dự án xác nhận hoặc thay bằng bài toán thực trước Gate W1. Mỗi demo phải có repository đích và dữ liệu mẫu không nhạy cảm.
