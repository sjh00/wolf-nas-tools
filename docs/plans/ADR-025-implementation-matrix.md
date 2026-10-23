# ADR-025 实现矩阵

> 对照：`docs/decisions/ADR-025-metadata-provider-and-naming-architecture.md`
> 日期：2026-10-20
> 状态说明：已实现 / 部分实现 / 未实现

## 1. 规范模型与 Provider

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| ProviderRef / FieldValue / ProviderRecord / MediaMetadata | 已实现 | `src/app/media/metadata/models.py` |
| 评分按 provider 命名空间 | 已实现 | `ratings` 字典 |
| 快照 schema_version | 已实现 | 模型与缓存 key 含版本 |
| PersonIdentity 人员实体 | 已实现 | 表/仓储/`/media/person/{id}` |
| Provider 协议 | 已实现 | `protocol.py` |
| ProviderContext | 部分实现 | 有 context/限流/熔断/URL 校验并传入 provider；内置 client 尚未全部走 context |
| map_ids 外部 ID 映射 | 部分实现 | 方法存在，调用链未使用 |
| health / provider 健康状态 | 已实现 | `/media/providers` 返回 health + runtime |
| 统一错误语义 | 已实现 | `errors.py` + orchestrator 降级 |
| 熔断器 / 超时策略 | 已实现 | provider 级失败计数/冷却；超时仍由 HTTP 层控制 |
| allowed_hosts / SSRF 防护 | 已实现 | `validate_outbound_url` + descriptor allowed_hosts |

## 2. 合成与策略

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| 字段级合成 | 已实现 | 顺序、locale、union、provenance |
| 预设策略 | 已实现 | tmdb/douban/bangumi/provider_only |
| 自定义字段策略 | 部分实现 | 订阅可传 `metadata_policy`；无完整策略编辑器 |
| 冲突记录 | 已实现 | `extra["conflicts"]` |
| 冲突人工审核 API | 已实现 | `/identity/conflicts` + `/identity/link/review` |
| 能力过滤 | 已实现 | orchestrator 从 descriptor 生成能力表 |
| 手动锁定字段 | 已实现 | `MEDIA_FIELD_OVERRIDE` 读取/写入，override 失效快照 |
| 锁定字段 | 已实现 | 仓储读写 + 合成读取；无独立前端页 |

## 3. 身份与订阅

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| MEDIA_IDENTITY / MEDIA_EXTERNAL_REF | 已实现 | 含 LINK_METHOD/CONFIDENCE/REVIEWED |
| MEDIA_METADATA_SNAPSHOT | 已实现 | `persist` + TTL 复用 + 落库 |
| 旧数据回填 | 已实现 | dry-run / apply / 幂等 |
| 订阅新增列 + 双写 | 已实现 | model/repository/adapter/service 全链路 |
| 锚点跟随卡片来源 | 已实现 | DB:/BG:/tmdb: 透传 |
| 锚点策略解析 | 已实现 | 创建时写入，读侧 helper 存在 |
| 订阅 UI 展示/编辑策略 | 未实现 | 前端仍按 tmdbid，策略字段未编辑 |
| 历史表 identity 列 | 已实现 | 两表新增列 + 迁移（写入仍待业务调用） |
| 跨源链接人工审核 | 已实现 | pending/review/merge |
| identity 合并/去重工具 | 已实现 | `merge_identity` + `/identity/merge` |

## 4. 识别与匹配

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| MatchProfile 协议 | 已实现 | `matching.py` |
| 内置 movie/tv/anime profile | 已实现 | 复用旧 `infer_type` |
| 插件 profile 优先级 | 已实现 | registry + parser 接入 |
| ParserProfile 内容编号识别 | 部分实现 | 接口与注册存在；解析器未实际调用 |
| content_profiles 注册表 | 部分实现 | 可注册，未参与解析/命名选择 |
| 匹配策略按内容形态替换 | 未实现 | 仍以旧 infer_type 结果为主 |

## 5. 刮削 / NFO / 图片

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| 快照驱动 Scraper | 已实现 | 无 TMDB 或关闭 legacy 时走快照 |
| 旧 TMDB 路径兼容 | 已实现 | `legacy_tmdb_fallback` 默认 true |
| 快照 NFO（movie/tv/season/episode） | 已实现 | 多 uniqueid、credits、ratings |
| NFO Profile 插件贡献 | 已实现 | `NfoProfile.extra_tags` 接入 NFO |
| 图片 resolver + fallback | 已实现 | provider 优先级/分辨率/locale/失败重试 |
| 演员图远程后端下载 | 部分实现 | 远程后端跳过演员图 |
| 分集整体展开 | 已实现 | 多季按需展开 + TMDB 缓存 |
| 豆瓣 HTML 分集 | 已实现 | PoW + 解析 + 队列 + TTL |
| 豆瓣 HTML 队列可观测 | 部分实现 | 有 stats，但无 API/指标 |

## 6. 命名

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| 核心字段扩展 | 已实现 | doubanid/bgmid/provider/评分等 |
| naming 命名空间字段校验 | 已实现 | `{profile.field}` + 插件字段目录 |
| NamingProfile 注册 | 已实现 | 注册/注销/字段目录 |
| 插件字段实际渲染 | 已实现 | `render_naming_fields` 合并进 format dict |
| profile 默认模板选择 | 未实现 | 仍由媒体库配置模板决定 |
| ParserProfile | 已实现 | ParserChain + UnifiedParser 短路；命名联动仍由 MatchProfile 决定 |
| 快照驱动命名 | 已实现 | 重命名规划器读取最新快照 |

## 7. Discovery / 探索页

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| DiscoveryProvider 注册表 | 已实现 | 协议/注册/注销 |
| 豆瓣/TMDB/Bangumi 内置 feed | 已实现 | 热映/趋势/季度/日历 |
| 季度档 seasonal | 已实现 | 日期区间换算 |
| `/discovery/providers` `/items` | 已实现 | 权限过滤 |
| 动态来源 tab + feed tab | 已实现 | 前端已重构 |
| 私有来源权限 | 已实现 | required_permission 动态校验 |
| feed 缓存 | 已实现 | 5 分钟 TTL |
| 用户来源/feed 偏好记忆 | 已实现 | localStorage |
| facet | 部分实现 | season + year；类型/演员未做 |
| 综合跨源视图 | 未实现 | 未做显式聚合 tab |
| 插件自定义面板 | 部分实现 | 有 `PluginSlot`，无内置示例 |

## 8. API / 数据库 / 安全

| ADR 条目 | 状态 | 说明 |
|---|---|---|
| `/metadata/preview` | 已实现 | 合成预览 |
| `/media/providers` | 已实现 | 能力/health/runtime |
| `/media/search`（多源） | 已实现 | registry 聚合搜索 |
| `/media/lookup` | 已实现 | 统一 ref 查询 |
| `/identity/{id}` `/conflicts` | 已实现 | 详情/待审/审核/合并 |
| `/naming/profiles` | 已实现 | profile + 字段列表；preview 仍走 name_format |
| 新表 + 迁移 | 已实现 | identity/ref/snapshot/override |
| 历史表新增 identity 列 | 已实现 | 两表列 + 迁移；业务写入待调用 |
| manifest 元数据自动装载 | 已实现 | `backend.metadata.*.entry` 自动实例化/注册 |
| 私有 zip 安全解压 | 已实现 | 路径穿越/符号链接拒绝 |
| 私有包 required_permission | 已实现 | descriptor 注入 + API 校验 |
| 私有包 SHA-256 校验 | 已实现 | 安装接口可选参数 |
| provider 级缓存/限流/熔断 | 已实现 | orchestrator 缓存 + runtime 限流/熔断 |
| 可观测性 | 部分实现 | metrics + 事件 ring buffer + `/metadata/metrics`；无外部事件总线 |

## 9. 运营与收尾

| 条目 | 状态 |
|---|---|
| 真实库迁移 | 未执行（仅临时 SQLite） |
| 回填 `--apply` | 未在真实库执行 |
| 生产 Redis/代理/风控验证 | 未执行 |
| P7 物理删除旧 TMDB 分支 | 保留观察期 |
| 前后端提交 | 未提交 |
| 全量测试 | 3625 passed / 6 skipped |

## 结论

主链路（Provider → 合成 → 身份 → 订阅 → 刮削/NFO → 探索页）已经可用。
尚未完成的主要是：人员实体、ProviderContext/限流熔断、跨源链接审核、历史表 identity 列、NamingProfile 实际渲染、多源搜索/统一 lookup API、可观测性，以及真实库迁移与提交。
