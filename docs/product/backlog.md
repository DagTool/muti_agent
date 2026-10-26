# Product backlog W1 — dự thảo

**Ưu tiên:** Must là điều kiện nghiệm thu v1.0; Should tăng chất lượng và khả năng vận hành; Could chỉ làm khi các gate chính ổn định. Trạng thái ở đây là kế hoạch, không tự động đồng nghĩa đã triển khai.

| ID | Ưu tiên | Hạng mục | Phụ thuộc | Bằng chứng hoàn tất |
|---|---|---|---|---|
| B01 | Must | PRD, use cases, acceptance và demo được owner duyệt | — | Quyết định Gate W1 |
| B02 | Must | Identity, RBAC, workspace scoping | B01 | Test quyền và cross-workspace |
| B03 | Must | Task DAG/state machine, lease, retry, cancel | B01, B02 | Test transition, crash/rebalance |
| B04 | Must | Outbox, Kafka routing, idempotency, DLQ | B03 | Integration/chaos tests |
| B05 | Must | PM/Architect output có schema, approval scope | B03 | Demo PRD → design → backlog |
| B06 | Must | Developer branch/worktree, allowlist và PR | B03, B05 | PR với diff gắn task |
| B07 | Must | Sandbox QA, defect loop tối đa 3 vòng | B06 | Log/test/defect evidence |
| B08 | Must | Dashboard task, activity, approvals, artifacts | B02–B07 | E2E và accessibility checks |
| B09 | Must | Token/cost budget, audit, secret scan | B02, B05–B07 | Budget/security tests |
| B10 | Must | CI, staging approval, backup/restore, hai demo | B04–B09 | CI, UAT và handover |
| B11 | Should | OIDC/invitation và token lifecycle production | B02 | Security review |
| B12 | Should | Model router nhiều provider và đánh giá output | B05, B09 | Routing/fallback tests |
| B13 | Should | Metrics, tracing, lag/recovery dashboard | B04, B08 | Dashboard và runbook |
| B14 | Could | WebSocket hai chiều | B08 | Nhu cầu người dùng và prototype |

## Trình tự gần nhất

1. Duyệt W1 và tạo issue/board cho B01–B10.
2. Chốt kiến trúc, threat model và test strategy W2.
3. Củng cố B02–B04 trước khi mở rộng chạy model hoặc quyền repository.
4. Kiểm thử B05–B10 với hai demo; không đánh dấu đạt nếu thiếu API key, repository đích hoặc bằng chứng UAT.

**Bản prototype hiện tại:** một số phần của B02–B09 đã có ở local. Xem [README](../../README.md) và [next steps](../architecture/next-steps.md) để phân biệt phần đã kiểm thử với mục tiêu v1.0.
