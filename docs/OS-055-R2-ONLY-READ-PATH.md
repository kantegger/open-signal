# OS-055: 公开读路径全面 R2 化与 Neon 成本治理

状态: Phase 1–2 已实现（Phase 0 / 3 待运行时验收）
前置: OS-048（滚动出版）、OS-049（生产编排）、OS-053（典藏保留）、OS-054（繁中出版）

## 目标与背景

现状: 首页与 Claim 页已经是 "R2 快照优先、FastAPI→Neon 兜底"。
但 Explore、Topic、期次典藏、SEO 索引四类公开页面**只有** API→Neon 一条路
（见 `apps/web/lib/server-api.ts` 中 `fetchTopicServer` /
`fetchExploreServer` / `fetchEditionArchiveServer` / `fetchSeoIndexServer`）。
后果:

1. 任何爬虫或读者访问这些页面都会唤醒 Neon，5 分钟自动挂起形同虚设，
   计费下限被读侧而不是批处理决定。
2. 这些页面没有快照兜底，API 或数据库故障时直接不可用，
   违反本项目"已发布内容永远可读"的原则。

目标状态: **Neon 只在每小时批处理时醒来**；所有公开读默认命中 R2；
FastAPI 降级为长尾兜底与运维接口。

原则不变: 数据库仍是权威（system of record）；R2 仍是读优化出版层；
期次对象不可变，频道指针可变且最后移动（与 `PublicationDelivery` 现有
`_put_immutable` / `_put_mutable_if_changed` 语义一致）。

## 分阶段执行

每个阶段独立可交付、可回滚。按顺序做，但 Phase 0 随时可先做。

---

### Phase 0 — Neon 计算设置（10 分钟，零代码）

执行:

1. 登录 Neon 控制台 → 项目 `open-signal` → Branch `production` → Compute 设置。
2. Scale to zero（自动挂起）延迟调到当前套餐允许的最小值。
3. Autoscaling 下限确认为 0.25 CU；上限不超过 1 CU（本负载用不到更多）。
4. `test` 分支同样处理。

验收: Neon 控制台 Monitoring 页观察 24 小时，
compute hours 应接近 `24 × (批处理时长 + 挂起延迟)`，不再出现整点之外的长时间活跃。

回滚: 控制台改回原值。

---

### Phase 1 — 频道级快照: Explore / 期次典藏 / SEO 索引

范围: 只快照**默认视图**（第一页、无筛选）。带 `cursor` / `year` / 翻页参数的
长尾请求继续走 API 兜底——爬虫和真实用户的绝对主流是默认视图。

#### 1a. Worker 侧（Python）

改 `python/open_signal/publication/delivery.py`:

1. `PublicationKeys` 增加三个键:
   - `public/publications/channels/explore/{locale}.json`
   - `public/publications/channels/editions/{locale}.json`
   - `public/publications/channels/seo-index.json`（无 locale，纯 URL 清单）
2. `deliver()` 在写完 claim 投影之后、移动 front-page 指针**之前**，
   用 `_put_mutable_if_changed` 写入这三个对象。数据来源直接复用现有 presenter:
   - Explore: `python/open_signal/api/explore.py`
   - 典藏首页: `python/open_signal/api/editions.py`（archive 查询, limit=50）
   - SEO 索引: 现有 `/api/seo-index` 的查询逻辑
3. 繁中口径: explore/editions 使用 `locale` 参数复用现有本地化投影；
   这些视图的字符串来自已翻译的 proposition/边栏字段，
   **不新增 DeepSeek 调用**（列表页出现英文回退是可接受的中间态，
   因其正文最终落在已翻译的 Claim/front-page 上）。

先写测试（TDD，参照 `apps/worker/tests/test_publication_delivery.py` 现有模式）:

- 交付后三个频道键存在且在指针之前写入（断言 `store.put_order`）。
- 数据未变时第二次交付不重写（`_put_mutable_if_changed` 语义）。
- Explore presenter 失败时不阻塞 front-page 交付（快照缺失可接受，指针照常移动；
  记录 warning 即可，不 raise）。

#### 1b. Web 侧（Next.js）

改 `apps/web/lib/server-api.ts`，给三个函数加 R2 优先分支，
完全照抄 `fetchCurrentFrontPageServer` 的结构（R2 读失败且配了
`OPEN_SIGNAL_API_URL` 时才回落 API）:

- `fetchExploreServer`: 仅当 `topicPage === 1 && signalPage === 1 && !asOf`
  时走 R2 键 `channels/explore/{locale}.json`，否则直接 API。
- `fetchEditionArchiveServer`: 仅当无 cursor/year/section/status 筛选时走 R2。
- `fetchSeoIndexServer`: 始终优先 R2。

缓存标签保持现有命名（`explore`、`edition-archive`、`seo-index`），
`revalidate` 秒数不变。

#### 1c. 失效通知

改 `apps/web/app/api/revalidate/route.ts`: webhook 处理时追加

```ts
revalidateTag("explore", { expire: 0 });
revalidateTag("edition-archive", { expire: 0 });
revalidateTag("seo-index", { expire: 0 });
```

Worker 侧 revalidate POST 的 payload 不需要改（webhook 是整体失效）。

#### 1d. 验收

```powershell
# 交付一轮后，三个键可直接读取
$base = "https://pub-663344cb96044648a00527ba459d1a03.r2.dev"
Invoke-RestMethod "$base/public/publications/channels/explore/en.json"
Invoke-RestMethod "$base/public/publications/channels/explore/zh-Hant.json"
Invoke-RestMethod "$base/public/publications/channels/editions/en.json"
Invoke-RestMethod "$base/public/publications/channels/seo-index.json"

# 页面正常渲染（生产）
Invoke-WebRequest https://os.yhleo.com/explore | Select-Object StatusCode
Invoke-WebRequest https://os.yhleo.com/editions | Select-Object StatusCode
```

硬验收: 在 Vercel web 项目临时移除 `OPEN_SIGNAL_API_URL` 环境变量后，
`/explore`、`/editions`、`/zh-Hant/explore` 首屏仍然可用（长尾筛选页允许降级）。
验完恢复该变量。

回滚: revert web 侧 commit 即回到 API 直读；R2 上多出的频道对象无害，可留置。

预估: 1–2 天（含测试）。

---

### Phase 2 — Topic 页快照（可变投影，仿 Claim current 模式）

Topic 是长尾 URL，不能整体预生成，采用与
`public/publications/claims/{id}/{locale}.json` 相同的"当前投影"模式:

#### 2a. Worker 侧

1. `deliver()` 收集当前期次引用的全部 topic id
   （render plan item 的 `topic.id`，参见 `api/editions.py` `_item()`）。
2. 对每个 topic，用 `ClaimPagePresenter` 同级的 topic presenter
   （`python/open_signal/api/topics.py`）构建 payload，
   `_put_mutable_if_changed` 写入
   `public/publications/topics/{topic_id}/{locale}.json`。
3. 只写当期引用的 topic。历史 topic 的旧投影自然留在 R2
   （内容是当时的真实快照，符合不可变精神）；从未被出版引用过的 topic
   继续走 API 兜底。

测试: 当期 topic 投影被刷新、未引用 topic 不写、
第二次交付内容不变时跳过写入。

#### 2b. Web 侧

`fetchTopicServer` 加 R2 优先分支，键
`public/publications/topics/{topicId}/en.json`（topic 页当前仅英文数据，
繁中界面词由前端处理），失败回落 API。

#### 2c. 失效通知

worker 交付 payload 已含 `claim_ids`；同批把 topic id 列表加进 revalidate
POST body（`python/open_signal/publication/delivery.py` 中 `self.client.post`
的 json），webhook 对每个 id 执行
`revalidateTag(`topic:${id}`, { expire: 0 })`。

#### 2d. 验收

```powershell
# 从当前 front-page 取一个 topic id 后:
Invoke-RestMethod "$base/public/publications/topics/<topic-id>/en.json"
```

同样做"移除 `OPEN_SIGNAL_API_URL` 后当期 topic 页仍可用"的硬验收。

预估: 1 天。

---

### Phase 3 — 观察期与量化确认（一周，零代码）

1. DeepSeek 翻译缓存: 交付几轮后读取最新
   `public/publications/editions/{id}/localization.zh-Hant.os-l10n-002.json`，
   确认 `usage.cache_hit_count` 持续上升、`estimated_cost_usd` 趋近于零。
2. Neon: 控制台确认 compute hours 降到"仅整点批处理"的形状；
   记录 Phase 0/1/2 前后的月度预估账单数字。
3. Vercel: FastAPI 函数调用量应下降一个数量级
   （仅剩长尾筛选、历史 topic、运维端点）。

若第 3 点成立，在 `docs/DEPLOYMENT.md` 把 FastAPI 的角色改写为
"长尾兜底与运维接口"，公开读路径以 R2 为准。

---

### Phase 4（可选，独立决策）— 厂商收敛

前三阶段完成后，Vercel FastAPI 已无承重职责，存在两个后续选项，
均**不属于本路线的承诺范围**，仅记录方向:

- 小步: web 保留在 Vercel，仅停用 API 项目的公开路由（保留 ops token 路由）。
- 大步: 整体 Cloudflare 原生化（Workers + D1 + Queues），
  即此前评估过的重写路线——量级为周，收益是收敛到单一厂商。
  详见当次评估结论: D1 额度足够，但需要重写约 1.8 万行 Python 管线、
  46 表 schema 与 plpgsql 触发器，属于重构而非迁移。

## 风险与边界

- **快照滞后**: 参考部署的频道快照最多每四小时随交付刷新，与现状的 ISR 900–3600 秒相比
  时效略降。可接受: 这些页面本就展示"上一次出版"的状态。
- **交付失败**: 频道/topic 快照写失败不得阻塞 front-page 指针移动
  （出版主承诺优先）；失败后下一轮交付自然补齐。
- **R2 对象数增长**: 每轮新增写入 ≤ 3 个频道对象 + 当期 topic 数个投影，
  Class A 操作与存储成本均可忽略。
- **不做的事**: 不快照带筛选参数的长尾视图；不为繁中列表页新增翻译调用；
  不动每小时出版节奏。

## 完成定义

1. 移除 `OPEN_SIGNAL_API_URL` 的情况下，
   首页 / Claim / Explore / 典藏 / 当期 Topic（含 `/zh-Hant`）全部可读。
2. Neon 月度 compute hours 曲线只剩整点脉冲。
3. `docs/DEPLOYMENT.md` 架构图与角色描述已更新。
