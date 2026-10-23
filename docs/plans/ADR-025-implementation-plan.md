# ADR-025 实施计划

> 分支：`feature/adr-025-metadata-engine`
> 依据：`docs/decisions/ADR-025-metadata-provider-and-naming-architecture.md`
> 状态：P0–P7 完成；收尾补齐完成；全量回归 3625 passed；快照落库已实测；P7 物理删除待观察期

## 拆分原则

- 每个 PR 保持单一逻辑变更，测试随模块提交；
- P0–P3 不改变任何对外行为，旧 TMDB 路径保持原样；
- feature flag 控制新链路（`metadata.provider_engine` 等），可随时关闭回退；
- 每阶段完成标准是**可验证的测试**，不是代码写完。

## P0 元数据内核（当前）

目标：建立 provider 无关的 DTO、注册表、合成器，不接任何线上链路。

| # | 任务 | 文件 | 状态 |
|---|---|---|---|
| P0-1 | DTO：ProviderRef / ProviderRecord / MediaMetadata / 能力枚举 | `src/app/media/metadata/models.py` | 完成 |
| P0-2 | 错误语义 | `src/app/media/metadata/errors.py` | 完成 |
| P0-3 | Provider / Profile 注册表（线程安全、插件归属、注销） | `src/app/media/metadata/registry.py` | 完成 |
| P0-4 | 合成策略预设与锚点解析 | `src/app/media/metadata/policy.py` | 完成 |
| P0-5 | 字段级合成器 + provenance + 冲突记录 | `src/app/media/metadata/composer.py` | 完成 |
| P0-6 | 单元测试（18 个用例） | `tests/unit/test_metadata_*.py` | 完成 |
| P0-7 | ruff / pyright / pytest 通过 | - | 完成 |

验收：

- `tmdb_primary` / `douban_primary` 合成结果符合预期；
- 豆瓣主源缺 seasons/episodes 时由 TMDB 记录补齐；
- 评分为命名空间字典，不合并；
- 每个字段带 provider/external_id/confidence；
- 插件注册/注销幂等，内置 key 不可被覆盖；
- 不修改现有任何调用方。

## P1 联调记录（2026-10-20）

| 场景 | 结果 |
|---|---|
| 电影 TMDB `278` + 豆瓣 `1292052`，`tmdb_primary` | 标题/日期/时长取自 TMDB，评分命名空间 `{tmdb:8.733, douban:9.7}` |
| 同上，`douban_primary` | 标题/简介取豆瓣，日期/时长/图片取 TMDB |
| 剧集 TMDB `100088` + 豆瓣 `25848328` | seasons=2、episodes=9；`tmdb_primary` 标题「最后生还者」，`douban_primary` 标题「最后生还者 第一季」 |
| Bangumi 日历首项 | subject detail 正常返回中文名/评分/海报 |
| 缺失 provider 引用 | `degraded=true`，其他源正常输出 |
| `POST /api/media/metadata/preview` | 直接调用返回 `code=0`，快照可 JSON 序列化 |
| 私有 provider 无权限 | 返回「无权访问私有来源」 |

联调中发现并修复：

1. locale 过滤覆盖 provider 顺序，导致 `tmdb_primary` 标题取豆瓣；
2. `release_date/runtime/poster` 预设顺序写反；
3. 季标题与主标题被误报为冲突（包含关系不再算冲突）。

已知限制（进入 P3 处理）：

- TMDB adapter 目前只拉当前季（默认 S1）的分集，多季剧集需按 season 展开；
- 豆瓣 HTML 分集（含 PoW/Cookie）尚未接入；
- Bangumi search 未实现（仅 detail）；
- 无 Redis 时缓存回退会带来额外连接等待，生产环境需保证 Redis 可用。

## P1 Provider 适配与编排

| # | 任务 | 说明 |
|---|---|---|
| P1-1 | `MetadataProvider` / `DiscoveryProvider` / `MatchProfile` 协议 | 完成 |
| P1-2 | TMDB provider adapter | 完成（映射 + adapter 类 + 测试） |
| P1-3 | 豆瓣 provider adapter | 完成（frodo API + 日期守卫，HTML 分集待接） |
| P1-4 | Bangumi provider adapter | 完成（subject detail 映射） |
| P1-5 | `MetadataOrchestrator` | 完成（并行取数/降级/能力映射；熔断缓存 P6） |
| P1-6 | 合成预览 API | 完成（`POST /api/media/metadata/preview`） |

验收：同一 identity 可分别用三源合成，输出稳定 hash。

## P1 能力补齐（2026-10-20）

| 能力 | 状态 | 实测 |
|---|---|---|
| TMDB 多季分集 | 完成：文件季号写入 `scope=season=N`，adapter 按季拉取 | TMDB S2 返回 7 集，全部 `season_number=2` |
| 豆瓣 HTML 分集 | 完成：PoW 求解 + 分集页解析 + TTL 缓存，刮削时按需展开 | S1 前两集中文名/首播日正常 |
| Bangumi search | 完成：`v0/search/subjects`，provider 映射 SearchHit | 「孤独摇滚」返回 5 条 |


## P2 身份与订阅

| # | 任务 | 说明 |
|---|---|---|
| P2-1 | `MEDIA_IDENTITY` / `MEDIA_EXTERNAL_REF` / 快照/覆盖表 + Alembic | 完成（`eb2e213b5ce3`，upgrade/downgrade/check 已验证） |
| P2-1b | 身份仓储 + `MetadataService` + DI + 预览服务化 | 完成（API → Service → Provider/Repository 分层） |
| P2-2 | 数据回填 | 完成：只读试跑 + `--apply`，幂等，支持 dry-run 报告 |
| P2-3 | 订阅表新增列 + 双写 | 完成：模型/迁移/repository/adapter/service 全链路，保留 TMDBID |
| P2-4 | 订阅锚点规则 | 完成：写 anchor + 读路径 `resolve_subscription_policy`，实体/查询透出 |
| P2-5 | douban sync 去桥接 | 完成：豆瓣无 TMDB 可订阅；refresh 跳过非 TMDB 锚点 |

## P3 刮削与 NFO

| # | 任务 | 说明 |
|---|---|---|
| P3-1 | Scraper 快照驱动 | 完成：无 TMDB 时走 `compose_for_media` + 快照渲染 |
| P3-2 | NFO 快照渲染 | 完成：movie/tvshow/season/episode + 多 uniqueid |
| P3-3 | ImageResolver | 完成：provider 优先级 + 分辨率 + locale + 失败 fallback + 演员图 |
| P3-4 | 兼容回退 | 完成：有 TMDB 仍走旧路径 |

## P4 探索与订阅入口

| # | 任务 | 说明 |
|---|---|---|
| P4-1 | DiscoveryProvider 协议 + registry | 完成：feed/facets/items + 私有来源过滤 |
| P4-2 | `/api/media/discovery/*` | 完成：providers/items + 权限过滤 |
| P4-3 | 内置 feed 基线 | 完成：豆瓣榜单、Bangumi 日历/新番、TMDB 趋势/季度档 |
| P4-4 | 探索页两级信息架构 | 完成：来源 tab → feed tab → 季度筛选 → 动态卡片 |
| P4-5 | 卡片订阅 | 完成：卡片按 anchor_ref 生成 DB:/BG:/tmdb: mediaid，订阅确认走通用接口 |

## P4 前后端联调记录（2026-10-20）

环境：临时 SQLite + 真实 TMDB/豆瓣/Bangumi，后端 `:3000`，前端 Vite `:5555`。

| 检查项 | 结果 |
|---|---|
| 登录 → 排行榜 | 200，来源 tab 显示豆瓣/TMDB/Bangumi |
| 豆瓣 movie_showing | 20 条，海报经 `/img/douban/...` 代理返回 200 |
| TMDB 趋势 | 20 条 |
| TMDB 季度新剧 `2026-q4` | 20 条，季度选择器可见 |
| Bangumi 季度新番 `2026-q4` | 106 条 |
| 豆瓣卡片订阅 `DB:37247814` | 订阅创建成功 |
| 订阅身份双写 | identity 同时写入 douban（primary）与 tmdb ref |
| 前端控制台 | 仅 Iconify CDN 被环境阻断，无业务错误 |

联调中修复：

1. 豆瓣卡片订阅只写 douban ref → 改为 anchor + TMDB 匹配 ref 双写；
2. 豆瓣海报直连 418 → `MediaCard` 统一走 `getImgUrl` 本地代理；
3. 浏览器首屏等待不足导致误判空白 → 以真实卡片/图片加载完成作为验收。

## P5 匹配与命名扩展

| # | 任务 | 说明 |
|---|---|---|
| P5-1 | MatchChain + MatchProfile | 完成：插件优先级、置信度阈值、解析器接入 |
| P5-2 | 内置 profile 迁移 | 完成：movie/tv/anime 内置 profile，结果复用 infer_type |
| P5-3 | NamingProfile 注册 | 完成：命名空间字段、插件注册/注销、字段目录 API |
| P5-4 | get_format_dict 扩展 | 完成：新增 provider/评分字段，支持可选 snapshot；调用方按需传入 |

## P6 插件运行时

| # | 任务 | 说明 |
|---|---|---|
| P6-1 | manifest `backend.metadata` 解析 | 完成：providers/discovery/content/match/parser/naming/nfo |
| P6-2 | `ctx.register_*` API | 完成：声明校验、注册、批量注销 |
| P6-3 | 插件启停集成 | 完成：卸载注销 + cleanup 回调 + provider `on_unregister` 钩子 |
| P6-4 | 私有 provider pack | 完成：zip 安全解压、visibility 强制、required_permission、打包脚本 |

## P7 清理

- `legacy_tmdb_fallback` 开关已落地（默认 True）：关闭后 Scraper 与订阅刷新不再走 TMDB 旧桥接；
- 最终删除旧分支需至少两个 minor 版本观察，暂不执行物理删除。

## 收尾补齐（2026-10-20）

| 项 | 状态 |
|---|---|
| 快照落库/复用 | 完成：`persist/max_age_seconds`，同 hash 去重，override 变更失效；实测写入 1 条快照 |
| 手动 override | 完成：合成前读取 `MEDIA_FIELD_OVERRIDE` 并作为 locked 字段 |
| 订阅策略消费 | 完成：创建订阅时按 anchor 写入 `douban_primary/tmdb_primary/bangumi_primary` |
| 命名快照驱动 | 完成：重命名规划器读取 identity 最新快照并传入 `get_format_dict` |
| provider 缓存 | 完成：orchestrator 30 分钟 TTL，provider 注销后不再命中 |
| discovery 缓存 | 完成：feed 5 分钟 TTL + 手动 clear |
| 私有权限 | 完成：`required_permission` 注入 descriptor 并由 API/Service 校验 |
| zip 哈希校验 | 完成：安装接口支持 `sha256` 表单字段 |
| 前端插件面板 | 完成：探索页 `PluginSlot target="discovery.panels"` |

仍未完成（运营/后续）：


- provider 级熔断器与独立 QPS；
- 真实库迁移、回填 `--apply`、全量部署验证；
- P7 物理删除旧 TMDB 分支（观察期）。

## 风险与前置

- P2 迁移前必须完成 P0/P1 并有回滚演练；
- 豆瓣 HTML 分集依赖 PoW 求解器与短时 Cookie，放在 P1 之后单独实现，不阻塞主链路；
- 探索页改造依赖前端仓库同步，接口先稳定。
