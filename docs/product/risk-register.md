# Risk register W1 — dự thảo

| ID | Rủi ro | Tác động | Giảm thiểu và tín hiệu kiểm tra | Chủ trì đề xuất |
|---|---|---|---|---|
| R01 | Agent sửa ngoài phạm vi hoặc lộ secret | Cao | Allowlist, symlink checks, sandbox, secret scan, review PR | Security/owner |
| R02 | Kafka giao lặp, crash hoặc rebalance làm nhân đôi tác động | Cao | Outbox, idempotency, lease, chaos tests | Backend/operator |
| R03 | Quyền workspace bị vượt qua API hoặc stream | Cao | Authz mọi endpoint, cross-workspace tests, audit | Backend/security |
| R04 | Model sinh output sai schema hoặc mã lỗi | Cao | Schema validation, QA sandbox, defect loop, người duyệt | Agent/QA |
| R05 | Token/cost vượt ngân sách | Trung bình/cao | Cap trước request, cảnh báo, tính usage, kiểm tra request đồng thời | Owner/operator |
| R06 | Không có API key hoặc repository đích để nghiệm thu live | Cao cho tiến độ | Tiếp tục mock/local; ghi gate chưa kiểm chứng, lấy điều kiện từ owner | Owner |
| R07 | Mở PR/deploy khi test hoặc approval chưa đạt | Cao | Gate trên state machine/CI, branch protection, audit | Owner/DevOps |
| R08 | Mất trạng thái khi worker/DB restart | Cao | Checkpoint, migration, backup/restore và recovery test | Operator |
| R09 | Phạm vi 16 tuần phình ra vì thêm agent/tính năng | Trung bình | Giữ MoSCoW, review hàng tuần, bảo vệ acceptance gate | Product owner |

**Rà soát:** cập nhật xác suất, người chịu trách nhiệm thực tế, ngày kiểm tra và tình trạng mỗi tuần; không coi cột giảm thiểu là bằng chứng đã triển khai.
