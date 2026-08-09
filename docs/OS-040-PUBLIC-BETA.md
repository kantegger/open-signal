# Public Beta Release（OS-040）

## 发布范围（in scope）

| 页面/能力 | 说明 |
|---|---|
| 首页（Daily Edition） | 三个 Section 的每日编排：Expectations Moved / Rules Moved / Research Frontier |
| 三个 Section | `expectations-moved`、`rules-moved`、`research-frontier`（shadow/beta 成熟度） |
| Archive | 历史 Edition 快照（`daily_editions` 只读） |
| Claim 页面 | `/claims/{id}`：Observation / Analysis / Assessment / Evidence / Counterevidence / Agent lineage / Claim ID / Version history |
| Method | 方法页：数据源（Polymarket / Federal Register / OpenAlex / ClinicalTrials）、流程、弃权与护栏说明 |
| System Status | `/api/ops/*`（需 `Authorization: Bearer`）：Edition、Source Health、Job Queue、Agent Runs、Daily Cost、Feature Flags、Claims Corrected |

## 明确不发布（out of scope）

- 账户系统
- 付费
- 提醒（email/webhook）
- 公开 API（当前只读 API 仅内部/前端使用）
- 完整 Scorecard

## 上线检查清单

运行 `python scripts/release_check.py`（需 `OPEN_SIGNAL_DATABASE_URL`）：

1. `alembic_version == 0010`（全部迁移）
2. `DEEPSEEK_API_KEY` 已配置（LLM Agent）
3. `OPEN_SIGNAL_OPS_TOKEN` 已配置且不少于 32 字符（ops 端点认证，fail-closed）
4. 关键表有数据：`sources`、`daily_editions`、`claims`、`feature_flags`、`audit_events`
5. 最近 7 天有 Edition 产出
6. 无 `ops.mode.*` 降级标志（normal 模式）
7. 无 retracted/degraded 来源

## 部署步骤

```powershell
# 1. 迁移
$env:OPEN_SIGNAL_DATABASE_URL = "..."
python -m alembic -c infra/migrations/alembic.ini upgrade head

# 2. 环境变量（生产）
# OPEN_SIGNAL_DATABASE_URL, DEEPSEEK_API_KEY, OPEN_SIGNAL_OPS_TOKEN

# 3. 启动 API（只读）
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

# 4. 前端（Next.js）
# OPEN_SIGNAL_API_URL=http://<api>/ ; npm run build && npm start

# 5. 发布前检查
python scripts/release_check.py
```

## Ops 认证配置

`OPEN_SIGNAL_OPS_TOKEN` 是 Open Signal 自行生成的服务端共享密钥，不是第三方
API Key。它只应配置在运行 FastAPI 的环境中，不得使用 `NEXT_PUBLIC_` 前缀，
也不得提交到仓库。

本地 PowerShell：

```powershell
$env:OPEN_SIGNAL_OPS_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m uvicorn apps.api.main:app --port 8000
```

标准请求方式：

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/ops/current-edition" `
  -Headers @{ Authorization = ("Bearer " + $env:OPEN_SIGNAL_OPS_TOKEN) }
```

旧客户端可在迁移期继续发送 `X-Ops-Token: <token>` 或历史的
`X-Ops-Token: Bearer <token>`；新代码不得继续依赖该私有请求头。若标准头与
旧请求头同时出现且内容不同，服务端拒绝请求。

生产环境须在 API 托管平台的 Secret / Environment Variables 中设置该值，并在
更新后重启或重新部署 API。Preview 与 Production 应使用不同密钥；若 Vercel
仅托管 Next.js 前端，则不要把该密钥配置到前端项目。

## 回滚

- **Edition 错误**：`EditionWriter.correction()` / `rollback()` 生成新行（`correction_count` 递增），不改历史
- **来源撤回**：`RetractionHandler.run_retraction()` → canonical retired → claim degraded → edition corrected → archive 记录
- **LLM 成本失控**：`BudgetGuard` hard limit → `deterministic_only`；或 `DegradedModeManager.set_mode("archive_only")`
- **数据库**：Alembic downgrade（`alembic downgrade -1`），`daily_editions` 只追加
