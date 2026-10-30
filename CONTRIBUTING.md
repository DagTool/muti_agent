# Đóng góp cho AgentForge AI

Repository đang ở giai đoạn prototype. Mỗi thay đổi cần mô tả phạm vi, bằng chứng kiểm tra và các giới hạn còn lại để người duyệt phân biệt hành vi đã chứng minh với mục tiêu trong kế hoạch.

## Nhánh và Pull Request

1. Tạo nhánh từ `main` với tiền tố `feat/`, `fix/`, `docs/` hoặc `test/`; một PR giải quyết một mục đích rõ.
2. Liên kết backlog/issue và UC/AC khi có. Nêu trạng thái trước/sau, tác động tới schema/event contract, cách rollback và gate phê duyệt.
3. Không đưa `.env`, token, khóa API, dữ liệu cá nhân hoặc log chứa secret vào commit/PR. Dùng dữ liệu mẫu không nhạy cảm.
4. CI xanh là điều kiện kỹ thuật; owner vẫn phải duyệt scope, staging và bàn giao theo workflow. Không tự đánh dấu Gate W1 hay các gate v1.0 hoàn tất.

## Quy ước mã

- **Python:** hỗ trợ Python 3.11+, dùng type hints và Ruff với `line-length = 100`. Đặt business state trong PostgreSQL qua API/services; worker không suy ra trạng thái từ Kafka offset.
- **Event:** thay đổi `EventEnvelope` hoặc topic phải nêu version/migration và cách xử lý consumer cũ. Kafka giao at-least-once; tác động nghiệp vụ phải idempotent theo event/attempt.
- **Database:** thay đổi model cần migration Alembic có đường upgrade/downgrade và kiểm tra từ DB trống. Không sửa migration đã áp dụng nếu có thể thêm revision mới.
- **Frontend:** React/TypeScript dùng trạng thái loading/error/empty rõ, kiểm tra quyền trên API thay vì tin UI. Không lưu API key trong browser storage.
- **Sandbox:** đường dẫn file phải nằm trong workspace, chặn symlink escape; mã sinh chạy trong sandbox với giới hạn tài nguyên và mạng theo cấu hình.

## Kiểm tra trước PR

Chạy phần bị ảnh hưởng; ghi kết quả thật trong PR.

```powershell
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\python -m pytest -q
.venv\Scripts\alembic check
cd apps/web
npm run build
```

`alembic check` cần PostgreSQL local; xem [README](README.md) để khởi động hạ tầng. Với thay đổi migration, chạy thêm `python -m scripts.check_fresh_migration`. Với thay đổi worker/event, bổ sung kiểm thử duplicate, retry hoặc crash tương ứng. Không thêm test chỉ lặp lại chi tiết triển khai; tập trung vào hành vi có rủi ro.

## Review

Reviewer xem contract, quyền workspace, idempotency, rollback, secret exposure và test evidence trước khi đề nghị merge. Các thay đổi kiến trúc lớn cần một [ADR](docs/architecture/ADR-template.md) ghi bối cảnh, phương án và hệ quả.
