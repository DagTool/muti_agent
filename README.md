# AgentForge AI

Nền tảng thử nghiệm cho kế hoạch trong [tài liệu gốc](AgentForge_AI_Ke_Hoach_Phat_Trien_Chi_Tiet.md). Checkout này có dashboard React, project/requirement/run/approval API, PostgreSQL outbox, Kafka dispatcher và workflow mock. Chế độ OpenAI tùy chọn đã có PM, Architect, Developer sinh một dự án Python nhỏ và QA chạy kiểm thử trong sandbox Docker. API có RBAC local qua token `owner`/`member`/`viewer`. Đây vẫn chưa phải bản v1.0: chưa có đăng nhập OIDC, GitHub PR, staging, đo chi phí tiền tệ hay kiểm thử chấp nhận trên hai dự án mẫu.

## Chạy local

Yêu cầu: Docker Compose, Python 3.11+, Node.js 20+.

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

Mở bốn terminal khác, kích hoạt `.venv` rồi chạy:

```powershell
python -m workers.outbox_worker
python -m workers.dispatcher_worker
python -m workers.agent_worker --role developer
python -m workers.agent_worker --role qa
python -m workers.recovery_worker
```

Trong một terminal khác, chạy giao diện:

```powershell
cd apps/web
npm ci
npm run dev
```

Dashboard: <http://127.0.0.1:5173/>. Nhập `AGENTFORGE_API_KEY` từ `.env` vào ô API key. Key chỉ nằm trong bộ nhớ tab, không lưu trong browser storage. API docs: <http://127.0.0.1:8000/docs>. Workspace mặc định được tạo bởi migration và có ID `local-dev`.

`AGENTFORGE_API_KEY` là khóa bootstrap của owner. Owner có thể cấp token cá nhân qua `POST /api/v1/members` với `email`, `name`, `role` (`owner`, `member`, `viewer`). Token chỉ trả về một lần, lưu trong DB ở dạng SHA-256 và hết hạn sau 30 ngày. `viewer` chỉ đọc; `member` có thể tạo project/yêu cầu/run/task và hủy hoặc thử lại run; `owner` còn được duyệt approval, chỉnh ngân sách, đổi vai trò và thu hồi token. Các API quản lý nằm trong `/docs`. Đây là RBAC local, chưa có OIDC, email invitation hoặc đăng nhập bằng mật khẩu.

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
.venv\Scripts\python -m scripts.smoke_ai_execution
```

Unit tests dùng SQLite tạm thời. `smoke_ai_execution` cần Docker và kiểm tra đường đi sinh file mẫu → Git commit → QA sandbox, không gọi OpenAI API. `npm run build` kiểm tra TypeScript và frontend bundle. Chế độ mock chỉ mô phỏng kết quả; không gọi LLM hoặc tạo PR.

## Chế độ OpenAI

Đặt `AGENTFORGE_AGENT_MODE=openai` trong `.env` trước khi tạo run mới. Cấp `OPENAI_API_KEY` cho **process worker** bằng biến môi trường của hệ điều hành; không nhập khóa này vào dashboard hay lưu vào Git. Có thể chọn model bằng `AGENTFORGE_OPENAI_MODEL` (mặc định `gpt-6.1-sol`). Khởi động lại API, dispatcher và workers sau khi đổi chế độ. Chạy bốn role `pm`, `architect`, `developer`, `qa` cùng recovery worker:

```powershell
python -m scripts.create_topics
python -m workers.agent_worker --role pm
python -m workers.agent_worker --role architect
python -m workers.agent_worker --role developer
python -m workers.agent_worker --role qa
python -m workers.recovery_worker
```

PM tạo PRD và chờ duyệt scope. Architect tạo thiết kế, Developer sinh tối đa 30 file Python/tài liệu vào `.agentforge/projects/<project>/<run>` và tạo Git commit cục bộ. QA chạy `compileall` và `unittest` trong container không có mạng; kết quả và commit cuối được lưu vào artifact. Dashboard cho xem từng file trong phạm vi run. Nếu QA thất bại, run bị chặn và có thể thử lại tối đa 3 lần sau khi sửa file trong workspace. Các lệnh model không được chạy trực tiếp trên host. Docker sandbox hiện phù hợp với môi trường local do người dùng tin cậy; cần ranh giới cô lập mạnh hơn trước khi cho phép yêu cầu từ người dùng không tin cậy.

Mỗi project có ngân sách token mặc định 500.000. API và dashboard ghi nhận input/output token của từng task, cho phép điều chỉnh giới hạn. Đây là giới hạn **mềm**: các request đang chạy đồng thời có thể vượt mức và lỗi model không trả usage có thể chưa được tính. Hệ thống chưa quy đổi token thành chi phí tiền tệ vì đơn giá phụ thuộc model và hợp đồng API.

## Workflow hiện có

1. Tạo project và lưu một phiên bản requirement.
2. Tạo run: hệ thống lưu bản scope mock và mở approval `scope`.
3. Duyệt scope: tạo task Developer qua outbox/Kafka. Developer mock hoàn tất và tạo task QA.
4. QA mock hoàn tất, lưu báo cáo và mở approval `handover`.
5. Duyệt handover: run chuyển `completed`. Từ chối hoặc hủy run được lưu bền vững và audit.

Các task còn được kiểm tra `event_id` để tránh xử lý lặp khi Kafka giao trùng. Recovery worker đưa task OpenAI bị treo quá 10 phút về hàng đợi với `attempt` mới, tối đa 3 lần. Kafka và PostgreSQL đang dùng cấu hình local một node; trước khi dùng cho người dùng thật cần OIDC, kiểm soát multi-tenant và ranh giới sandbox mạnh hơn.
Dispatcher tách topic Developer/QA của chế độ mock và OpenAI theo `mode` cố định của từng run, để task cũ vẫn được xử lý đúng sau khi đổi cấu hình. Khi chuyển chế độ, cần khởi động worker tương ứng cho các run còn đang hoạt động.

`python -m scripts.smoke_local` kiểm tra end-to-end toàn bộ luồng mock khi API và workers đang chạy. Dashboard hiển thị activity timeline từ audit log, artifacts, mã nguồn trong run và số token model đã dùng.

## Cấu trúc

- `apps/api`: API và business state.
- `apps/web`: React dashboard.
- `packages/communication`: event contract, Kafka topics.
- `workers`: outbox publisher, dispatcher, mock/OpenAI workers, recovery worker.
- `packages/agent_runtime`: OpenAI Responses adapter và schema đầu ra.
- `packages/execution`: kiểm tra file sinh ra và Docker sandbox.
- `infra`: Compose local (PostgreSQL, Redis, Kafka KRaft).
- `docs`: phạm vi, ADR và các bước tiếp theo.

Không đưa `.env` hoặc secrets vào Git. Compose hiện dành cho phát triển local, chưa có cấu hình bảo mật/HA cho staging hay production.

Tắt dịch vụ local (giữ lại volumes dữ liệu): `docker compose --env-file .env -f infra/compose.dev.yaml down`.
