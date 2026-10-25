# AgentForge AI

Nền tảng thử nghiệm cho kế hoạch trong [tài liệu gốc](AgentForge_AI_Ke_Hoach_Phat_Trien_Chi_Tiet.md). Checkout này triển khai **vertical slice đầu tiên**: tạo project/task qua FastAPI, ghi task và outbox trong cùng giao dịch PostgreSQL, phát lệnh qua Kafka, dispatcher định tuyến tới developer worker, worker mẫu xử lý idempotent và cập nhật task. Đây chưa phải bản v1.0 hay hệ thống chạy mã AI.

## Chạy local

Yêu cầu: Docker Compose, Python 3.11+.

```powershell
Copy-Item .env.example .env
# Đổi AGENTFORGE_API_KEY trong .env trước khi dùng ngoài máy cá nhân.
docker compose --env-file .env -f infra/compose.dev.yaml up -d --wait
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m scripts.create_topics
.venv\Scripts\python -m uvicorn apps.api.app.main:app --reload
```

Mở ba terminal khác, kích hoạt `.venv` rồi chạy:

```powershell
python -m workers.outbox_worker
python -m workers.dispatcher_worker
python -m workers.agent_worker
```

API docs: <http://127.0.0.1:8000/docs>. Mọi request `/api/v1` cần header `X-API-Key` với giá trị `AGENTFORGE_API_KEY` trong `.env`. Workspace mặc định được tạo bởi migration và có ID `local-dev`.

LangGraph mock riêng: `python -m scripts.demo_graph` (in memory) hoặc `python -m scripts.demo_graph --postgres` (checkpoint trong PostgreSQL).

```powershell
$headers = @{ 'X-API-Key' = 'replace-with-a-long-random-value'; 'Idempotency-Key' = 'project-demo-1' }
$project = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/projects -Headers $headers -ContentType application/json -Body '{"name":"Demo API","description":"Task API"}'
$headers['Idempotency-Key'] = 'task-demo-1'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/projects/$($project.id)/tasks" -Headers $headers -ContentType application/json -Body '{"title":"Mock developer task","role":"developer"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/projects/$($project.id)/tasks" -Headers $headers
```

## Kiểm thử

```powershell
.venv\Scripts\python -m pytest
```

Unit tests dùng SQLite tạm thời. Kafka/PostgreSQL local cần được chạy riêng để kiểm tra toàn tuyến. Worker hiện chỉ mô phỏng một kết quả có kiểm soát; không thực thi shell, không gọi LLM và không tạo PR.

## Cấu trúc

- `apps/api`: API và business state.
- `packages/communication`: event contract, Kafka topics.
- `workers`: outbox publisher, dispatcher, mock developer worker.
- `infra`: Compose local (PostgreSQL, Redis, Kafka KRaft).
- `docs`: phạm vi, ADR và các bước tiếp theo.

Không đưa `.env` hoặc secrets vào Git. Compose hiện dành cho phát triển local, chưa có cấu hình bảo mật/HA cho staging hay production.
