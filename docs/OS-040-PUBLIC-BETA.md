# Public Beta Release（OS-040）

## 发布范围（in scope）

| 页面/能力 | 说明 |
|---|---|
| 首页（Daily Edition） | 三个 Section 的每日编排：Expectations Moved / Rules Moved / Research Frontier |
| 三个 Section | `expectations-moved`、`rules-moved`、`research-frontier`（shadow/beta 成熟度） |
| Archive | 历史 Edition 快照（`daily_editions` 只读） |
| Claim 页面 | `/claims/{id}`：Observation / Analysis / Assessment / Evidence / Counterevidence / Agent lineage / Claim ID / Version history |
| Method | 方法页：数据源（Polymarket / Federal Register / OpenAlex / ClinicalTrials）、流程、弃权与护栏说明 |
| System Status | `/api/ops/*`（需 `X-Ops-Token`）：Edition、Source Health、Job Queue、Agent Runs、Daily Cost、Feature Flags、Claims Corrected |

## 明确不发布（out of scope）

- 账户系统
- 付费
- 提醒（email/webhook）
- 公开 API（当前只读 API 仅内部/前端使用）
- 完整 Scorecard

## 上线检查清单

运行 `python scripts/release_check.py`（需 `OPEN_SIGNAL_DATABASE_URL`）：

1. `alembic_version == 0008`（全部迁移）
2. `DEEPSEEK_API_KEY` 已配置（LLM Agent）
3. `OPEN_SIGNAL_OPS_TOKEN` 已配置（ops 端点认证，fail-closed）
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

## 回滚

- **Edition 错误**：`EditionWriter.correction()` / `rollback()` 生成新行（`correction_count` 递增），不改历史
- **来源撤回**：`RetractionHandler.run_retraction()` → canonical retired → claim degraded → edition corrected → archive 记录
- **LLM 成本失控**：`BudgetGuard` hard limit → `deterministic_only`；或 `DegradedModeManager.set_mode("archive_only")`
- **数据库**：Alembic downgrade（`alembic downgrade -1`），`daily_editions` 只追加
