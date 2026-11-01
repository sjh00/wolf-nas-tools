# ADR-025: 多源元数据订阅与刮削架构（Provider / Composition / Naming Profile）

## Status

Proposed

## Date

2026-10-19

## Context

### 现状：TMDB 是事实上的唯一元数据主键

当前搜索、订阅、刮削、转移、重命名共享同一条隐式假设：**作品身份 = TMDB ID**。

- `MediaInfo` 只有 `tmdb_id` / `tmdb_info` 能承载完整详情，豆瓣、Bangumi 只作为查询或兜底。
  （`src/app/media/models.py`）
- `Scraper` 没有 `tmdb_info` 直接判定无法识别并跳过。
  （`src/app/media/scraper/__init__.py`）
- `NfoGenerator` 的所有字段直接读取 TMDB 字典；`uniqueid` 固定为 `tmdb`。
  （`src/app/media/scraper/nfo_generator.py`）
- 添加订阅时，拿不到 TMDB 信息即返回「TMDB无法查询到媒体信息」；豆瓣订阅刷新时会被强制转换成 TMDB。
  （`src/app/services/subscribe/management/add_service.py`、`refresh_service.py`）
- 订阅表以 `TMDBID` 为事实主键，`SUBSCRIBE_MOVIES` / `SUBSCRIBE_TVS` 的唯一约束也围绕它。
  （`src/app/db/models/subscribe.py`）
- 重命名字段目录硬编码为 `tmdbid` / `imdbid`，渲染字典只从 `MediaInfo.tmdb_id` 取值。
  （`src/app/services/transfer/name_format.py`、`path_resolver.py`）
- `MediaType` 只有 `movie` / `tv` / `anime` / `unknown`，无法表达垂直内容需要的内容形态与命名体系。
  （`src/app/domain/mediatypes.py`）

这套模型在只有一个主数据源时最简，但无法满足以下新需求：

1. 豆瓣可以独立作为订阅与刮削主源，TMDB 只补缺失字段；
2. TMDB 作为主源时，豆瓣补充中文标题、简介、评分等本地化字段；
3. 后续可接入 Bangumi、TVDB、Fanart、垂直内容 provider 等；
4. 不同内容形态可以使用不同的命名规则与 NFO 约定；
5. 新增 provider 与命名规则应通过插件完成，而不是继续修改核心枚举和 `if provider == ...`。

### 根因

**元数据来源、作品身份、字段合成、命名渲染四件事被混在了 `MediaInfo.tmdb_info` 一个结构里。**
只要引入第二个主源，任何直接读 `tmdb_info` 的代码都会成为阻塞点。

### 与既有 ADR 的关系

- 本 ADR 复用 ADR-014 的 `Work / Alias / Franchise / EditionGraph` 作为识别层，不重新实现匹配算法。
- 本 ADR 在 ADR-014 之上新增**跨 provider 的稳定身份**、**字段级合成**、**命名/NFO 扩展点**。
- 本 ADR 遵循 ADR-021：provider 缓存与合成快照属于全局资源，用户订阅只保存引用与策略。

## 目标

1. **来源无关**：订阅、刮削、转移、重命名不再要求 TMDB；任何已注册 provider 都可以作为主源。
2. **字段级合成**：支持 `豆瓣为主 + TMDB 补齐`、`TMDB 为主 + 豆瓣补齐`、`单源直出`、`多源按字段优先级合成`。
3. **身份稳定**：本地作品身份不依赖任何单一外部 ID；外部 ID 是一等多值属性。
4. **可插件化**：provider、命名 profile、解析 profile、NFO profile 均可由插件贡献，核心不感知垂直内容细节。
5. **可兼容**：现有 TMDB 数据、订阅、下载历史、NFO、命名模板在迁移期继续可用。
6. **可解释**：每个字段都能追溯来源、置信度与抓取时间，冲突可预览、可手动锁定。

## 体验验收标准（"好用"的判据）

架构的正确性最终体现在用户可感知的结果上。本 ADR 的落地以以下体验指标为验收线：

1. **中文优先**：默认 `tmdb_primary` 下，卡片/订阅/NFO 的中文标题、中文简介、豆瓣评分由
   豆瓣字段级补充；从豆瓣卡片发起的订阅自动使用 `douban_primary`，所见即所得；
2. **无感兜底**：豆瓣有条目但 TMDB 没有时，订阅和刮削照常工作（单源直出）；
   TMDB 有条目豆瓣没有时亦然；用户不需要知道背后有几个源。
3. **剧集完整**：豆瓣订阅的电视剧，NFO 与媒体服务器里的分集名/日期/剧照完整
   （TMDB api tier + 豆瓣 html tier 补中文分集名），不出现「整季只有一集 NFO」。
4. **探索即订阅**：探索页任何卡片一键订阅/搜索，不强制跳详情页填写来源；
   来源 tab 动态出现，装了插件就多一个，卸了就少一个；
   排行榜按来源分区，不再出现豆瓣/TMDB 条目混排的页面。
5. **可修正**：识别错了能一键换匹配、按字段选来源、锁定后不被刷新覆盖；
   误识别可回退，不产生「改不了」的脏数据。
6. **命名可控**：模板预览所见即所得，新字段有目录可查，非法模板保存前就报错。
7. **不降级旧体验**：纯 TMDB 用户升级后，搜索、订阅、刮削、重命名的结果与升级前一致
   （回归测试 + 双写对比验证）。
8. **性能不劣化**：探索页首屏 P95 < 2s（feed 缓存命中），订阅添加不引入额外串行请求，
   刮削批量任务按 provider 并发上限执行。

### 非目标

- 不在本 ADR 内实现具体第三方站点适配。
- 不改变 ADR-014 的匹配算法与 EditionGraph 语义。
- 不把 provider 原始 JSON 长期写入订阅表。
- 不在核心仓库内维护垂直内容目录、站点名单或专用命名规则；此类能力通过独立插件包分发。

## 核心设计

### 1. 分层

```
订阅来源 / 文件名 / 媒体服务器 / 手动选择
              │
              ▼
       ReleaseParser（ADR-014）
              │ ParsedRelease
              ▼
       IdentityResolver（ADR-014）
              │ WorkCluster / MediaIdentity
              ▼
     MetadataOrchestrator（并行取数、限流、熔断）
              │ ProviderRecord[]
              ▼
      MetadataComposer（字段级合并 + 来源追踪）
              │ MediaMetadataSnapshot
              ├──────────────► Scraper → NFO / 图片 / 演员
              ├──────────────► NamingProfile → 目录与文件名
              └──────────────► API 预览 / 手动修正
```

四个边界必须分离：

| 层 | 职责 | 不做什么 |
|---|---|---|
| Provider | 把某个外部源转换为统一 DTO | 不决定最终标题、不写数据库 |
| Composer | 按策略合并字段、记录 provenance | 不发请求、不做身份匹配 |
| Identity | 判断「是不是同一部作品」 | 不决定字段优先级 |
| Naming / NFO | 消费已合成的规范数据 | 不直接访问 provider |

### 2. 规范元数据模型

核心不再使用 `tmdb_info` 作为数据载体，而是使用 provider 无关的 `MediaMetadata`。

```python
class ProviderRef(BaseModel):
    provider: str                 # tmdb / douban / bangumi / <plugin>
    external_id: str              # 统一字符串，避免各源 ID 类型不一
    media_type: MediaType | None = None
    scope: str = "default"        # 同一 provider 下的命名空间，如 tv/movie/person
    url: str | None = None
    confidence: float = 1.0


class FieldValue(BaseModel):
    value: Any
    provider: str
    external_id: str
    confidence: float = 1.0
    locale: str | None = None
    fetched_at: datetime
    locked: bool = False          # 用户手动锁定，合成时最高优先级


class MediaMetadata(BaseModel):
    schema_version: int = 1       # 规范模型版本，跨版本迁移时必须校验
    identity_id: str              # 本地稳定 ID（ULID）
    media_type: MediaType
    # 内容形态：决定 provider 候选、解析 profile、命名/NFO profile；
    # 不改变 media_type 的粗粒度语义（movie/tv/anime），插件可注册新值
    content_profile: str = "default"
    refs: list[ProviderRef]
    fields: dict[str, FieldValue]       # 标量规范字段 → 值 + 来源
    ratings: dict[str, float]           # {douban: 8.7, tmdb: 7.2}
    aliases: list[Alias]
    credits: list[Credit]
    seasons: list[SeasonMetadata]
    episodes: list[EpisodeMetadata]
    images: dict[str, list[ImageAsset]]
    extra: dict[str, Any]               # provider 扩展字段，命名空间隔离
    snapshot_hash: str
    fetched_at: datetime
```

规范字段（核心最小集）：

```text
title, original_title, sort_title, aliases
year, release_date, end_date, runtime
overview, tagline, original_language, countries, spoken_languages
genres, tags, networks, studios, labels, series
poster, backdrop, logo, thumb, fanart
ratings.<provider>
external refs
credits: director / actor / writer / producer / composer
seasons / episodes
```

约束：

- **ID 一律字符串**：TMDB 数字、豆瓣数字、ISBN、内容编号、UUID 都能承载。
- **评分按 provider 命名空间保存**，不再把豆瓣分写进 `vote_average` 冒充 TMDB 分；旧接口的 `vote_average` 只映射策略主源的评分，并显式标注来源。
- **扩展字段不得污染核心字段**：插件字段只能写入 `extra["<provider>.<field>"]` 或已注册的 profile 字段。
- **快照不可变**：每次抓取生成新 hash，订阅只引用 identity；旧快照可回溯。
- **schema 必须版本化**：provider 返回的原始缓存、发现项、规范快照都带 `schema_version`；缓存 key 与快照 hash 包含版本，模型演进时不混读旧结构。

### 3. Provider 协议

```python
class ProviderCapability(StrEnum):
    SEARCH = "search"
    DETAIL = "detail"
    EXTERNAL_IDS = "external_ids"
    SEASONS = "seasons"
    EPISODES = "episodes"
    CREDITS = "credits"
    IMAGES = "images"
    RELEASE_DATES = "release_dates"
    CONTENT_ID = "content_id"       # 以内容编号为锚点的垂直源
    ACTOR_DETAIL = "actor_detail"


class MetadataProvider(Protocol):
    descriptor: ProviderDescriptor

    def search(self, query: SearchQuery, ctx: ProviderContext) -> list[SearchHit]: ...
    def detail(self, ref: ProviderRef, ctx: ProviderContext) -> ProviderRecord | None: ...
    def map_ids(self, ref: ProviderRef, ctx: ProviderContext) -> list[ProviderRef]: ...
    def seasons(self, ref: ProviderRef, ctx: ProviderContext) -> list[SeasonRecord]: ...
    def episodes(self, ref: ProviderRef, season: int, ctx: ProviderContext) -> list[EpisodeRecord]: ...
    def health(self, ctx: ProviderContext) -> ProviderHealth: ...
```

`ProviderDescriptor` 至少包含：

```python
provider_key: str
display_name: str
capabilities: frozenset[ProviderCapability]
media_types: frozenset[MediaType]
content_profiles: frozenset[str]      # 空 = 通用
default_priority: int                 # 仅在策略未显式指定时使用
visibility: Literal["public", "private"]
result_schema_version: int
source_tiers: frozenset[Literal["api", "html", "scraping"]]   # 实现层级
requires_auth: bool = False        # 需要 Cookie/Token 才可达的能力
```

能力需要区分**实现层级**（`source_tier`）：同一能力（如 `EPISODES`）可以是官方 API
直出（稳定、高并发），也可以是 HTML 刮取（Cookie 风控、低并发、易漂移）。合成器按
`api > html > scraping` 的层级优先选择实现，同能力低层级实现仅作降级兜底。
html tier 的实现必须内置风控处理（如豆瓣的 PoW 挑战求解器与短时效 cookie 刷新，
见 `docs/research/douban-vs-tmdb-metadata.md` §3.2.1），并在风控命中时熔断降级，
不得在同步请求链路上反复重试。

### 3.1 ProviderContext 与错误语义

provider 只能拿到注入的运行时上下文，不能直接访问全局单例或数据库：

```python
class ProviderContext(Protocol):
    http: HttpClient                 # 已带超时/代理/重试限制
    cache: Cache                     # provider 专属命名空间
    rate_limiter: RateLimiter        # provider 专属配额
    config: Mapping[str, Any]        # 插件/系统配置，已脱敏
    logger: ProviderLogger           # 自动脱敏
    data_dir: Path                   # 插件私有数据目录
```

统一错误类型，前端与编排层按类型降级：

```python
ProviderNotFound        # 条目不存在
ProviderTimeout
ProviderUnavailable
ProviderRateLimited
ProviderParseError      # 响应结构变化/反爬
ProviderAuthError       # Cookie/Token 失效
ProviderSchemaError     # 返回 DTO 不符合 schema_version
```

约束：

- `ProviderTimeout/Unavailable/RateLimited` 触发熔断，不视为数据不存在；
- `ProviderNotFound` 可缓存较短的空结果，避免同一失败反复请求；
- `ProviderParseError/SchemaError` 需要记录并通知维护者；
- provider 不能抛裸异常给业务层，必须转换为上述错误。

### 3.2 人员实体

演员/导演/编剧是跨作品的一等实体，不应只作为作品字段字符串：

```python
class PersonIdentity(BaseModel):
    person_id: str                # 本地稳定 ID
    canonical_name: str
    aliases: list[str]
    external_refs: list[ProviderRef]
    images: list[ImageAsset]
    updated_at: datetime
```

- provider 可实现 `ACTOR_DETAIL` 能力，返回 `PersonIdentity`；
- 作品 `credits` 同时保留显示名与可选 `person_id`；
- 同名不同人通过 provider ref 区分，无 ref 时只按显示名展示，不强行合并；
- 人员缓存独立 TTL，支持手动刷新；插件可注册私有人员源。

内置 provider：

| key | 能力 | 说明 |
|---|---|---|
| `tmdb` | search/detail/ids/seasons/episodes/credits/images | 现有 `TmdbLookup` 适配 |
| `douban` | search/detail/ids/credits/images | 现有 `DoubanApi` / `DouBan` 适配 |
| `bangumi` | search/detail/ids/relations | 动漫别名与关系，服务 ADR-014 |

插件 provider 与内置 provider 使用同一个 registry，不允许业务代码直接 import 具体 provider 类。

### 4. Provider 注册与插件扩展点

核心提供扩展注册表（与现有 `api_registry` 同级的 `metadata_registry`）：

```python
ctx.register_metadata_provider(provider)
ctx.unregister_metadata_provider(provider_key)
ctx.register_naming_profile(profile)
ctx.register_parser_profile(profile)
ctx.register_nfo_profile(profile)
ctx.register_content_profile(profile)
```

manifest 新增声明：

```json
{
  "backend": {
    "metadata": {
      "providers": [
        {
          "key": "example",
          "entry": "backend.provider:ExampleProvider",
          "capabilities": ["search", "detail", "images"],
          "media_types": ["movie", "tv"],
          "content_profiles": [],
          "visibility": "public"
        }
      ],
      "discovery_providers": [
        {
          "key": "example",
          "entry": "backend.discovery:ExampleDiscovery",
          "feeds": ["popular", "latest"],
          "content_profiles": [],
          "visibility": "public",
          "required_permission": ""
        }
      ],
      "content_profiles": [
        {"key": "default", "entry": "backend.profiles:DefaultProfile"}
      ],
      "match_profiles": [
        {"key": "default", "content_profile": "default", "entry": "backend.match:DefaultMatchProfile"}
      ],
      "naming_profiles": [
        {"key": "default", "content_profile": "default", "entry": "backend.naming:DefaultNaming"}
      ],
      "parser_profiles": [],
      "nfo_profiles": []
    }
  }
}
```

注册规则：

1. 插件只能注册 manifest 中声明过的 key；注册表校验 `plugin_id` 与 key 的归属。
2. key 全局唯一；核心内置 key 不可被插件覆盖。
3. 插件禁用/卸载时按 `plugin_id` 批量注销，并清除其缓存命名空间、发现项缓存、人员缓存与限流状态。
4. provider 实现失败、超时或返回非法 DTO 时只降级该 provider，不中断整个合成。
5. provider 不直接访问 repository；需要数据时通过 `ProviderContext` 暴露的只读能力或返回 DTO。
6. 注册必须是**幂等且可热重载**：同 key 重复注册视为替换；插件升级时按新 `result_schema_version` 清理旧缓存；正在执行的任务完成或取消后切换新实例。

### 5. 合成策略（Composition Policy）

策略与 provider 解耦，订阅、刮削目录、API 预览都可以指定同一份策略。

```yaml
metadata_policy:
  primary: douban
  fallbacks: [tmdb]
  allow_partial: true
  conflict: primary_wins          # primary_wins | first_non_empty | manual
  fields:
    title:      {order: [douban, tmdb], locale: zh-Hans}
    overview:   {order: [douban, tmdb], locale: zh-Hans}
    poster:     {order: [tmdb, douban]}
    backdrop:   {order: [tmdb, douban]}
    runtime:    {order: [tmdb, douban]}
    genres:     {order: [tmdb, douban], merge: union}
    credits:    {order: [douban, tmdb], merge: union_by_name}
    ratings:    {order: [douban, tmdb], merge: namespaced}
```

预设：

| 预设 | 语义 |
|---|---|
| `douban_primary` | 豆瓣为主，TMDB 补齐图片、季集、IMDb/TVDB、英文标题 |
| `tmdb_primary` | TMDB 为主，豆瓣补齐中文标题、中文简介、豆瓣评分 |
| `bangumi_primary` | Bangumi 为主，TMDB 补齐剧集与图片（动漫） |
| `provider_only:<key>` | 单源直出，允许没有 TMDB ID |
| `custom` | 订阅或目录显式保存的字段策略 |

系统级默认预设为 `tmdb_primary`（与现状一致：结构完整、外部 ID 可靠，中文展示由豆瓣
字段级补充实现）。用户可在设置中切换为 `douban_primary`，单条订阅/单个媒体库根可覆盖。

**策略解析顺序**：订阅显式设置 > 锚点来源默认（见 6.4）> 系统默认。

### 5.1 数据源能力基线

字段策略不能只看优先级，还要看 provider 的**实测能力**。调研结论见
`docs/research/douban-vs-tmdb-metadata.md`，关键约束：

- **豆瓣无 seasons/episodes 能力**：剧集按季分条目，无分集名/日期/剧照；`douban_primary` 下
  `seasons/episodes/backdrop/logo/release_date` 必须强制 TMDB 兜底，与字段优先级无关。
- **豆瓣日期不可靠**：`pubdate` 是带地区标注的数组，可能是重映日（实测 1994 年电影返回
  `2026-08-28(中国大陆)`）；年份来源用 `year`，日期来源优先 TMDB `release_date`，
  豆瓣 `pubdate` 需地区过滤并排除晚于 `year` 超过 3 年的重映值。
- **豆瓣无 imdb_id**：跨源映射不能依赖豆瓣外部 ID，只能走 ADR-014 搜索匹配并进入
  `LINK_CONFIDENCE` 审核流程。
- **评分不可合并**：豆瓣评分（中文观众大样本）与 TMDB 评分差异大，必须命名空间共存。
- **能力声明驱动合成**：`ProviderDescriptor.capabilities` 缺少 `SEASONS/EPISODES` 的 provider
  不参与对应字段的竞争；`images` 标记为 `limited` 的 provider 不参与 backdrop/logo。

合成器内置一条硬规则：**字段优先级生效前先按 capability 过滤候选**。

合成算法：

1. **身份闸门**：只有通过 ADR-014 匹配，或存在精确 `ProviderRef` / 内容编号相等时，才允许合并。
2. **取数**：按 `primary + fallbacks` 并行请求，单 provider 超时/失败只记降级原因。
3. **规范化**：provider adapter 把原始响应映射成 `ProviderRecord`；禁止把原始 JSON 直接写入核心字段。
4. **字段求解**：
   - `locked` 手动值优先；
   - 按字段 `order` 取第一个非空值；
   - `locale` 不匹配时降级到无 locale 值；
   - 数组字段按 `merge` 规则合并（`union` / `union_by_name` / `primary_only`）；
   - 评分始终按 provider 命名空间并存；
   - 空值不覆盖已有值。
5. **来源记录**：每个最终字段写入 `FieldValue`，API 可展示「该值来自 douban:12345」。
6. **快照**：生成 `snapshot_hash`，缓存到 `MEDIA_METADATA_SNAPSHOT`，并回写 identity 的 refs。
7. **失败策略**：`allow_partial=true` 时返回部分快照；否则要求主源成功。

关键规则：

- **不允许用低置信度候选补齐主源**；补充源必须通过身份闸门。
- **不允许跨作品合并**：同 provider 同 ID 或 ADR-014 判定同一 Work 才可合并。
- **年份冲突不自动覆盖**：保留主源年份，冲突写入 `extra["conflicts"]` 供人工处理。

### 6. 稳定身份与订阅模型

#### 6.1 本地身份

新增 `MediaIdentity`，作为订阅、下载、转移、刮削共同引用的稳定对象：

```text
MEDIA_IDENTITY
  IDENTITY_ID (ULID, PK)
  MEDIA_TYPE
  CONTENT_PROFILE
  CANONICAL_TITLE
  YEAR
  CREATED_AT
  UPDATED_AT

MEDIA_EXTERNAL_REF
  ID
  IDENTITY_ID
  PROVIDER
  EXTERNAL_ID
  MEDIA_TYPE
  SCOPE
  URL
  CONFIDENCE
  LINK_METHOD          -- exact_ref / external_ids / search_match / manual
  LINK_CONFIDENCE      -- 0.0-1.0，低置信度不自动合并
  REVIEWED             -- 人工确认过的映射，后续刷新不降级
  IS_PRIMARY
  UNIQUE(PROVIDER, EXTERNAL_ID, SCOPE)
```

ADR-014 的 `Work` 继续负责别名、franchise、edition；`MediaIdentity` 是跨 provider 的本地聚合根。识别层命中 Work 后，通过 refs 解析或创建 `MediaIdentity`。

#### 6.2 订阅表扩展

`SUBSCRIBE_MOVIES` / `SUBSCRIBE_TVS` 增加：

```text
IDENTITY_ID          -- 本地身份
ANCHOR_PROVIDER      -- 订阅锚点来源，如 douban / tmdb
ANCHOR_EXTERNAL_ID   -- 锚点外部 ID
CONTENT_PROFILE      -- 内容形态，默认 default
METADATA_POLICY      -- 预设名或策略 JSON
NAMING_PROFILE       -- 可空，空则按内容形态取默认
```

兼容策略：

- `TMDBID` 保留为**派生兼容列**，由 identity 的 tmdb ref 回填；旧 API、旧查询、旧下载历史继续工作。
- 新增订阅优先写 `IDENTITY_ID + ANCHOR_*`；没有 identity 时创建。
- 唯一约束从 `(USER_ID, TMDBID, ...)` 演进为 `(USER_ID, IDENTITY_ID, SEASON)`；迁移期双写并保留旧索引。
- 对外 API 的 `mediaid` 支持 `tmdb:123`、`douban:456`、`bangumi:789`、`provider:id`；旧 `DB:` / `BG:` 继续解析。

#### 6.3 豆瓣订阅不再强制桥接 TMDB

`doubansync` 与手工添加订阅统一走：

```text
douban identity → MediaIdentity(douban ref) → metadata policy
```

- 若策略为 `douban_primary` 且 TMDB 未匹配，仍创建订阅，`TMDBID` 为空；
- 若之后 TMDB 匹配成功，只补充 ref 与快照，不改写订阅锚点；
- `refresh_rss_metainfo` 从「豆瓣转 TMDB」改为「刷新 identity 的 refs 与快照」。

#### 6.4 订阅锚点：跟随卡片来源

探索页/搜索页/详情页点击「订阅」时，**锚点 = 用户所看到的那张卡片的来源**：

```text
豆瓣卡片（douban:1292052）
  → anchor = douban:1292052
  → 创建/复用 MediaIdentity，写入 douban ref
  → metadata_policy 默认跟随锚点来源：douban → douban_primary
  → 后台异步尝试匹配 TMDB ref（不阻塞订阅创建）

TMDB 卡片（tmdb:278）
  → anchor = tmdb:278
  → metadata_policy 默认跟随锚点来源：tmdb → tmdb_primary
```

规则：

1. **用户从哪个源看到的，就用哪个源做主源**。豆瓣卡片订阅得到的展示与卡片一致
   （中文标题/简介/豆瓣评分），不会出现「点的是豆瓣卡片，详情却变成 TMDB 英文信息」。
2. 锚点源缺能力时照常合成兜底（如豆瓣锚点的剧集结构由 TMDB 补），策略只是字段优先级，
   不是能力开关。
3. 锚点创建后不随后台匹配结果改变；TMDB ref 匹配成功只补充 identity，不动 anchor 与策略。
4. 用户在订阅编辑页可显式切换策略（`douban_primary` / `tmdb_primary` / `custom`），
   显式设置后不再跟随锚点。
5. 搜索结果卡片必须携带来源 ref（`douban:` / `tmdb:` / `bangumi:`），前端透传；
   不允许把豆瓣卡片转成「标题+年份再搜 TMDB」的隐式桥接。

体验验收标准第 1 条的准确表述：**默认 `tmdb_primary` 保证结构与外部 ID 完整；
中文展示通过豆瓣字段级补充实现；从豆瓣卡片发起的订阅自动升级为 `douban_primary`。**

#### 6.5 匹配链插件化（MatchProfile）

现状：`type_inferrer.infer_type()` 硬编码 `SxxExx→TV / 年份→MOVIE / 制作组→ANIME`，
`MediaService` 再按 `MediaType` 分支走不同的 TMDB 匹配策略。新增内容形态必须改核心代码，
这是接新来源的主要障碍。

解耦为两层：

- `MediaType`（粗粒度文件形态，保持稳定）：movie / tv / anime / unknown，决定季集结构与 NFO 类型；
- `content_profile`（内容形态，**可插件注册**）：决定检测规则、解析策略、匹配策略、
  provider 候选、命名/NFO profile。动漫从「类型」降级为内置 profile `anime`，
  与未来的其他内容形态平级。

```python
class MatchProfile(Protocol):
    key: str                        # content_profile key，如 anime / music / documentary
    base_media_type: MediaType      # 兜底文件形态
    priority: int                   # 检测顺序，插件高于内置默认

    def detect(self, ctx: ParseContext) -> Detection | None:
        """文件名/上下文 → 命中则返回 Detection(confidence, anchor_hint)，未命中返回 None"""

    def match(self, parsed: ParsedRelease, ctx: ProviderContext) -> MatchResult:
        """ParsedRelease → provider 查询策略 + 打分 + 候选排序"""
```

匹配链执行顺序：

```text
文件名 → 通用预处理（资源标记/字幕组剥离，核心）
  → MatchProfile.detect 按 priority 降序（插件 profile 在前）
      高置信度命中 → content_profile + anchor_hint（如内容编号），跳过通用推断
      未命中 → 内置 infer_type（movie/tv/anime 兼容逻辑不变）
  → MatchProfile.match
      有 anchor_hint → provider 精确查询（内容编号/ID）
      无 → 标题+年份搜索 + profile 自定义打分
  → IdentityResolver → MediaIdentity
```

规则：

1. **检测短路**：profile 高置信度命中时不再走通用 `infer_type`，避免把内容编号误判为剧集；
2. **置信度阈值**：detect 置信度 < 0.85 视为未命中，回退通用推断，不产出半成品身份；
3. **作用域**：profile 可声明 `applies_to`（媒体库根/订阅来源/手动指定），
   默认 profile 不在普通媒体库启用垂直检测，防止误识别；
4. **内置兼容**：`movie` / `tv` / `anime` 作为内置 profile 保留现有全部行为；
   现有 `infer_type` 与 `MediaService` 的 anime 分支迁移为内置 `anime` profile 的实现，
   对外语义不变；
5. **匹配策略可替换**：profile 的 `match()` 决定查询与打分——动漫用季度+集数对齐，
   垂直内容用内容编号精确匹配，电影用标题+年份；
6. `MatchProfile` 与 `NamingProfile` / `NfoProfile` / `ParserProfile` 通过同一个
   `content_profile` key 关联，插件 manifest 一次声明整套形态。

### 7. 刮削管线

`Scraper` 从「TMDB 信息驱动」改为「快照驱动」：

```text
file → parse → identity（NFO / 下载历史 / 媒体服务器 / 在线识别）
     → MetadataOrchestrator.compose(identity, policy)
     → MediaMetadataSnapshot
     → NfoRenderer / ImageResolver / CreditsResolver
```

行为变化：

- 不再要求 `media_info.tmdb_info`；`douban_primary` 下可以只用豆瓣数据生成 NFO。
- NFO 的 `uniqueid` 为所有已知 ref 生成，例如 `tmdb`、`douban`、`bangumi`；`default="true"` 由策略的 primary 决定。
- `tmdbid` 标签仅在存在 TMDB ref 时输出，保持 Kodi/Emby/Jellyfin 兼容。
- 图片按字段策略选择，不再固定 TMDB → Fanart。
- 演职人员按 `merge` 规则合并，中文名匹配继续使用 `ChineseCredits`。
- provider 部分失败时仍可生成部分 NFO，并在日志/快照中标记 `degraded`。

NFO 渲染器重构为：

```text
NfoRenderer
  ├── CommonNfoWriter        # movie / tvshow / season / episode 通用字段
  ├── ProviderIdWriter       # uniqueid / tmdbid / imdbid / tvdbid
  ├── CreditWriter
  ├── RatingWriter           # 多 provider 评分
  └── ProfileNfoContributor  # 插件贡献的额外标签（可选）
```

### 7.1 图片解析与代理

`ImageResolver` 独立于 provider：

```text
provider 返回 ImageAsset(url/type/size/locale/provider)
  → 图片策略选择（poster/backdrop/logo/thumb/fanart/actor）
  → ImageProxy 下载、缓存、校验、转换
  → 落盘或写入媒体服务器
```

约束：

- 图片 URL 视为不可信：校验 Content-Type、尺寸、大小上限；不执行响应内容；
- 图片代理按 provider + schema_version + URL hash 命名空间缓存；
- 需要 Referer/Cookie 的源由 provider 声明，核心统一透传并脱敏；
- 私有来源使用独立缓存命名空间，不与公共来源混用；
- 下载失败按策略 fallback 到下一 provider，不阻塞 NFO 生成；
- 人工选择的图片作为手动锁定字段，自动刷新不得覆盖。

### 8. 命名规则扩展

#### 8.1 字段目录扩展

核心字段目录保留现有字段，并新增 provider 无关字段：

```text
doubanid, bgmid, provider, provider_id, content_profile
release_date, runtime, original_language
studio, label, series, actors, rating_douban, rating_tmdb
```

插件字段必须使用带命名空间的 key：

```text
{example.field}       # 语法扩展：key 允许 "."，仅注册过的字段可通过校验
```

原因：

- 避免插件字段与核心字段冲突；
- 插件卸载后旧模板会校验失败并给出明确提示，而不是静默渲染空值；
- 公共仓库不需要知道垂直字段名。

#### 8.2 NamingProfile

```python
@dataclass(frozen=True)
class NamingField:
    key: str                  # 可带命名空间，如 example.content_id
    label: str
    applies: str              # both / movie / tv / profile-specific
    resolver: Callable[[MediaMetadata, NamingContext], str | None]
    sanitizer: Callable[[str], str] | None = None
    required: bool = False


@dataclass(frozen=True)
class NamingProfile:
    key: str
    content_profile: str
    fields: tuple[NamingField, ...]
    default_movie: str
    default_tv: str
    default_tv_season: str
    parser_profile: str | None = None
    nfo_profile: str | None = None
```

- `NamingProfile` 由插件注册，核心只提供 `default` profile。
- 选择优先级：订阅显式设置 > 媒体库根设置 > `content_profile` 默认 > 系统默认。
- 校验：未知字段、未闭合条件段、跨 profile 字段混用均在预览阶段报错。
- 渲染：`get_format_dict` 改为从 `MediaMetadata` + 注册字段 resolver 构建，不再直接读 `MediaInfo.tmdb_id`。
- 兼容：现有 `{title}`、`{tmdbid}`、`{season_episode}` 等字段语义不变。

#### 8.3 ParserProfile

垂直内容往往需要先识别内容编号，再做元数据查询：

```python
class ParserProfile(Protocol):
    key: str
    content_profile: str
    priority: int

    def extract(self, title: str, subtitle: str) -> ParsedRelease | None: ...
```

- 核心在通用解析链之前按 `priority` 尝试已注册 profile；
- profile 高置信度命中时可直接生成 `anchor_ref`（内容编号），跳过通用标题匹配；
- 低置信度时回退到通用 `ReleaseParser`，避免误判；
- profile 必须声明 `applies_to`（媒体库根/文件名模式），默认不全局启用。

`ParserProfile` 是 `MatchProfile`（§6.5）的解析层组件：`ParserProfile.extract` 产出
`ParsedRelease` + `anchor_hint`，`MatchProfile.detect/match` 负责检测决策与打分。
同一 `content_profile` 的 Parser / Match / Naming / Nfo 由插件成套注册。

### 9. Discovery / Feed 扩展（探索页）

「探索」不是某个 provider 的专属页面，而是核心提供的**来源无关发现面**。
provider 除了元数据详情，还可以声明可浏览的 feed（热门、最新、榜单、标签、演员作品等）。

这是**通用能力，不是垂直内容专属能力**：内置的豆瓣、TMDB、Bangumi 排行榜/日历/热门，以及未来接入的 Trakt、AniList、MAL、第三方榜单或站点自建榜单，全部走同一套 `DiscoveryProvider` 注册与动态渲染。核心不再维护 `pageCategories` / `singlePageMap` 这类硬编码来源表。

`DiscoveryProvider` 与 `MetadataProvider` 是两个独立能力：

- 同一个来源可以同时实现两者（如 TMDB：既能搜索详情，也能提供热门/趋势）；
- 也可以只实现发现能力（只提供榜单，点击后交给其他 provider 补详情）；
- 还可以只实现元数据能力（不提供浏览页，只被订阅/刮削引用）。


```python
class DiscoveryProvider(Protocol):
    descriptor: DiscoveryDescriptor

    def feeds(self, ctx: ProviderContext) -> list[DiscoveryFeed]: ...
    def items(
        self,
        feed: str,
        page: int,
        filters: dict,
        ctx: ProviderContext,
    ) -> DiscoveryPage: ...
```

```python
class DiscoveryFeed(BaseModel):
    schema_version: int = 1
    key: str                    # 在 provider 内唯一，如 popular / latest / top_rated
    title: str                  # 展示名，由 provider 提供
    icon: str | None = None
    facets: list[Facet] = []    # 年份、标签、演员、厂牌等可筛选维度
    page_size: int = 20


class DiscoveryItem(BaseModel):
    schema_version: int = 1
    provider: str
    ref: ProviderRef            # 可回查详情的稳定引用
    content_profile: str
    title: str
    original_title: str | None = None
    year: str | None = None
    poster: str | None = None
    backdrop: str | None = None
    rating: dict[str, float] = {}   # 按 provider 命名空间
    tags: list[str] = []
    anchor_ref: ProviderRef | None = None   # 可直接用于订阅的锚点
    actions: list[str] = []     # subscribe / search / download / detail
    extra: dict[str, Any] = {}  # 命名空间扩展字段


class DiscoveryPage(BaseModel):
    items: list[DiscoveryItem]
    page: int
    has_more: bool
    facets: dict[str, list[FacetValue]] = {}
```

设计约束：

1. **feed 由 provider 声明，不由核心猜测**。核心不假设每个源都有 `popular`；provider 可以只提供 `latest`、`top_rated`、`by_tag`、`by_actress`。
2. **来源驱动 UI**：探索页从 `/api/media/discovery/providers` 拉取当前用户可见的 provider/feed，动态渲染来源标签、筛选器与卡片；不在前端硬编码来源名单。
3. **插件注入分两类**：
   - **数据注入（推荐）**：插件只注册 `DiscoveryProvider`，探索页使用核心通用卡片与筛选器渲染，不需要改前端；
   - **UI 注入（可选）**：需要特殊布局时，插件通过 `frontend.slots` 注册 `discovery.panels` 面板，核心只预留插槽，不感知内容。
4. **订阅入口统一**：卡片上的「订阅」调用通用订阅 API，携带 `anchor_ref + content_profile + metadata_policy`，不要求 TMDB。列表项没有 `anchor_ref` 时只显示「查看详情」，进入详情后再由 provider 解析锚点，禁止列表页为每个条目触发详情请求。
5. **私有来源**：`visibility: private` 的 provider 默认不出现在探索页；需要 `metadata:private:view` 权限或管理员，由后端过滤，不能只靠前端隐藏。
6. **缓存与限流**：feed 按 `provider + feed + page + filters` 缓存；provider 声明 TTL；单源失败不影响其他来源。
7. **无稳定榜单的来源**：只暴露实际可用的 feed，禁止伪造「热门」；例如只有搜索/分类能力的源可以提供 `search` / `by_tag` / `by_actress` 面板。

feed 类型（provider 声明，前端按类型选择通用渲染器）：

| kind | 语义 | 通用渲染 |
|---|---|---|
| `ranking` | 榜单/排行 | 带名次卡片 |
| `trending` | 趋势/流行 | 横向或网格卡片 |
| `latest` | 最新 | 时间倒序网格 |
| `calendar` | 日历/放送表 | 按日期分组 |
| `seasonal` | 季度档（新番/新剧/新片） | 季度切换器 + 网格 |
| `collection` | 专题/合集 | 分组卡片 |
| `search` | 源内搜索 | 搜索框 + 结果网格 |

#### 9.1 内置 feed 基线

现有探索页只有「豆瓣热门/TOP250、TMDB 趋势、Bangumi 周日历」，缺少用户高频使用的
**季度档**（每季新番、每季度新剧）。DiscoveryProvider 落地时，内置 provider 至少提供：

| feed | provider | kind | 实现 |
|---|---|---|---|
| 每季新番 | `bangumi` | seasonal | `air_date` 落在选定季度的动画条目（bangumi 搜索/标签接口），facet `season=2026-winter` |
| 每季新番（补充） | `tmdb` | seasonal | `discover/tv` + `with_genres=16` + `first_air_date.gte/lte=季度区间` |
| 每季度新剧 | `tmdb` | seasonal | `discover/tv` + `first_air_date` 季度区间 + `with_origin_country`/语言筛选 |
| 每季度新片 | `tmdb` | seasonal | `discover/movie` + `primary_release_date` 季度区间 |
| 季度华语剧 | `douban` | seasonal | `tv_recommend(tags=国产剧,2026)` / `subject_collection` 变体 |
| 放送日历 | `bangumi` | calendar | 现有 `/calendar` 按星期分组（保留） |
| 正在热映/即将上映/热门/Top250/口碑榜 | `douban` | ranking/trending | 现有 subject_collection 端点（保留） |
| TMDB 趋势 | `tmdb` | trending | 现有 trending/discover（保留） |

规则：

- `seasonal` feed 必须带 `season` facet，格式 `YYYY-q1..q4`（剧集/电影）与
  `YYYY-winter/spring/summer/fall`（新番，映射为 1/4/7/10 月季度）；
- 前端渲染统一的季度切换器（上一季/当季/下一季），facet 值透传 provider；
- 季度区间换算由核心完成（winter=01-01~03-31 等），provider 只接收日期区间；
- 默认选中「当季」；`seasonal` feed 按 `season + page` 缓存，TTL 6 小时；
- 这些内置 feed 只是 registry 数据，不是前端代码——新增/下线一个 feed 不改前端。

#### 9.2 探索页信息架构（排行榜重构）

现状问题：`/discovery/ranking` 把豆瓣热映、TMDB 趋势、豆瓣 Top250、口碑榜混排在一页，
来源语义不同（热度 vs 评分榜 vs 趋势），用户无法预期每一行是什么。

重构为两级结构，**来源是一级维度，feed 是二级维度**：

```text
探索
├─ 来源 tab：豆瓣 | TMDB | Bangumi | [插件来源...]     ← 由 /api/media/discovery/providers 动态生成
│   └─ feed tab：该来源自己声明的 feeds                 ← 由 feeds() 动态生成
│       └─ 内容区：按 feed.kind 选择通用渲染器 + facets 筛选
└─ 「综合」tab（可选，默认关）：跨源同 kind feed 的聚合视图，条目标注来源徽标
```

规则：

1. **不允许在同一内容区混排不同来源的条目**，除非用户显式进入「综合」tab；
   综合视图中每个条目必须带来源徽标，点击订阅时使用该条目自己的 anchor_ref。
2. 「排行榜」不再是独立硬编码页面，而是 kind=`ranking/trending` feed 的筛选视图
   （`/discovery?kind=ranking`），菜单保留入口但数据走同一协议。
3. 一级来源 tab 的顺序：内置来源在前（豆瓣/TMDB/Bangumi），插件来源按启用时间追加，
   私有来源按权限过滤；tab 数量多时折叠为下拉。
4. 记住用户上次选择的来源与 feed（本地偏好），下次进入直接恢复。
5. 空 feed 或 provider 降级时，tab 仍显示但内容区给出来源级错误提示，
   不影响其他来源。

动态 UI 契约：

- provider 返回 `feeds[]` 时同时声明 `kind / title / facets / page_size / render_hint`；
- 前端只实现少量通用渲染器（`grid`、`ranking_grid`、`calendar`、`list`），未知 `render_hint` 回退 `grid`；
- 新增来源不需要改前端代码，只需注册 provider 并返回 feed 描述；
- 现有豆瓣/TMDB/Bangumi 的硬编码分类逐步迁移为内置 `DiscoveryProvider`，迁移完成后删除前端 `pageCategories` / `singlePageMap`。

当前插件前端路由统一挂在 `/plugin` 下（`loader.ts` 的 `registerPluginRoutes`），因此要把入口放进「探索」：
- 首选核心探索页的通用 `discovery` 数据源机制；
- 需要整页自定义时，在探索页增加 `PluginSlot target="discovery.panels"`，插件注册该 slot；
- 不建议让核心新增 `/discovery/<source>-*` 之类硬编码路由。

订阅页同样保持通用：按 `content_profile` 与权限过滤订阅列表，插件只提供来源和命名 profile，不复制一套订阅管理页面。

### 10. API 变更

新增只读/预览接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/media/providers` | 当前用户可见 provider、能力、健康状态 |
| POST | `/api/media/search` | `{provider, query, media_type, content_profile}` |
| GET | `/api/media/lookup?ref=<provider>:<id>&policy=<key>` | 单条详情 |
| POST | `/api/media/compose/preview` | 返回合成后的规范字段与 provenance |
| GET | `/api/media/discovery/providers` | 当前用户可见的 discovery provider / feed / facets |
| POST | `/api/media/discovery/items` | `{provider, feed, page, filters}` → 标准化发现项 |
| GET | `/api/media/identity/{identity_id}` | identity、refs、快照摘要、冲突 |
| POST | `/api/media/identity/link/review` | 人工确认/拒绝跨源映射（`metadata:manage`） |
| GET | `/api/media/identity/conflicts` | 待确认映射与字段冲突列表 |
| GET | `/api/media/naming/profiles` | 可用命名 profile 与字段目录 |
| POST | `/api/media/naming/preview` | 模板 + 样本元数据 → 渲染结果 |

权限与可见性：

- `discovery:view` 控制探索页访问；
- `metadata:private:view` 控制 `visibility: private` 的 provider / feed / 订阅；
- 后端按权限过滤 provider 列表与发现项，前端隐藏不能作为安全边界。

订阅接口保持向后兼容：

- `mediaid` 支持新 ref 语法；旧 `DB:` / `BG:` / 纯数字继续映射。
- 新增可选字段 `anchor`、`metadata_policy`、`naming_profile`、`content_profile`。
- 返回值增加 `identity_id`、`refs`，`tmdbid` 继续返回（可为空）。

### 11. 数据库与迁移

新增表：

```text
MEDIA_IDENTITY
MEDIA_EXTERNAL_REF
MEDIA_METADATA_SNAPSHOT
MEDIA_FIELD_OVERRIDE       -- 手动锁定字段（用户/管理员）
PERSON_IDENTITY            -- 人员实体与别名
PERSON_EXTERNAL_REF        -- 人员跨源引用
```

历史表扩展：

- `DOWNLOADHISTORY` / `TRANSFERHISTORY` 增加 `IDENTITY_ID`、`ANCHOR_PROVIDER`、`ANCHOR_EXTERNAL_ID`、`CONTENT_PROFILE`；
- 迁移期双写，旧 `TMDBID` 继续保留；
- 重识别、目录改名、媒体服务器同步优先使用 identity/ref，旧列仅作兼容回退。

迁移步骤：

1. 建新表与索引；不修改现有列语义。
2. 从 `SUBSCRIBE_*`、`DOWNLOADHISTORY`、`TRANSFERHISTORY` 的 TMDBID 回填 identity + tmdb ref。
3. 从 `SUBSCRIBE_*` 的豆瓣来源（`DB:` 前缀、历史 note）回填 douban ref。
4. 订阅表新增列，双写；旧 `TMDBID` 继续由 ref 派生。
5. 新增唯一约束前先做重复 identity 合并（按 provider ref 精确匹配 + 年份 + 标题人工/规则复核）。
6. 回滚策略：关闭 `metadata.provider_engine` 后读旧列；新表保留不删除。

迁移要求遵循项目约定：revision ID 使用 `uv run alembic revision -m "..."` 生成，迁移后执行 `uv run alembic upgrade head` 与 `uv run alembic check`。

### 12. 缓存、限流与可观测性

- provider 缓存按 `provider:schema_version:ref:locale` 命名空间隔离，TTL 由 provider 声明。
- 单 provider 并发上限、QPS、超时、重试、熔断独立配置；不得让一个慢源拖垮整条识别链。
- 合成结果按 `identity_id + policy_hash + snapshot_hash` 缓存。
- 日志统一携带 `identity_id`、`provider`、`snapshot_hash`；provider 凭证与 Cookie 必须脱敏。
- 指标：provider 成功率、P95 延迟、降级次数、合成字段覆盖率、未匹配率。
- 事件：`metadata.provider.failed`、`metadata.snapshot.created`、`metadata.conflict.detected`，供插件与告警订阅。
- 刷新策略：快照 TTL 由策略声明；订阅刷新只拉取缺失或过期的 provider；手动刷新按 provider 粒度；低置信度映射不会自动重建。

### 13. 安全与插件边界

- provider 只能通过 `ProviderContext` 使用 HTTP、缓存、限流、配置与日志，不直接访问数据库或业务 repository。
- 出站域名由 manifest 声明 `allowed_hosts`，默认拒绝 localhost、内网地址与云元数据地址；重定向后重新校验。
- provider 返回值有大小上限与 schema 校验；非法响应视为失败，不写入快照。
- 插件凭证只存 `PLUGIN_CONFIG`，不得回显到日志、API 或 NFO。
- `visibility: private` 的 provider / profile 不进入公开市场列表，仅在安装并被管理员启用后可见；探索页与订阅列表同样按 `metadata:private:view` 在后端过滤。
- 新增权限码在 RBAC 初始化中登记（`metadata:private:view`、必要的 `metadata:manage`），角色配置后才可使用；插件不能自行绕过权限模型。
- 垂直内容插件使用独立仓库与独立分发渠道；核心仓库只保留通用扩展协议与空实现。

### 14. 实施阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 规范模型、Provider registry、TMDB/Douban/Bangumi adapter；旧路径不变 | 契约测试通过，旧功能零回归 |
| P1 | Composer + 策略 + provenance + preview API | `douban_primary` / `tmdb_primary` 合成矩阵测试通过 |
| P2 | `MediaIdentity` / `MEDIA_EXTERNAL_REF` / 快照表 + 数据回填 | 旧订阅可解析，新订阅可无 TMDB 创建 |
| P3 | Scraper/NFO 改为快照驱动；图片与演职人员统一 | 豆瓣单源可生成 NFO；TMDB 旧 NFO 兼容 |
| P4 | 订阅读写切换 identity；douban sync 不再强制桥接；探索页改为 provider/feed 驱动，内置 seasonal 基线（每季新番/季度新剧） | 豆瓣订阅无 TMDB 时仍可搜索、下载、转移；探索页来源可插拔；季度切换器可用 |
| P5 | NamingProfile / ParserProfile / MatchProfile 扩展；`infer_type` 与 `MediaService` 类型分支迁移为内置 profile；`get_format_dict` 改造 | 现有模板与识别结果零变化；插件 profile 可注册/卸载 |
| P6 | 插件 metadata + discovery 扩展点上线，私有 provider pack 接入 | 插件启停、缓存清理、权限与失败隔离通过 |
| P7 | 移除 legacy 分支（至少两个 minor 版本后） | 全量回归与迁移演练通过 |

每个阶段通过 feature flag 控制：

```text
metadata.provider_engine
metadata.douban_primary
metadata.snapshot_scraper
naming.profile_engine
discovery.provider_engine
```

### 15. 测试策略

- **Provider 契约测试**：统一 fixture 验证 search/detail/map_ids 的 DTO、错误、超时、空结果。
- **合成矩阵**：豆瓣主/TMDB 主/单源/部分失败/冲突/锁定字段/多语言。
- **身份测试**：同 provider 同 ID、跨 provider 映射、年份冲突、低置信度拒绝合并。
- **命名测试**：字段注册、命名空间、未知字段、可选片段、迁移前后模板等价。
- **NFO 测试**：多 uniqueid、缺失 TMDB、rating 命名空间、剧集/季边界。
- **迁移测试**：旧订阅、旧下载历史、`DB:` 前缀、重复 identity 合并。
- **插件测试**：注册/注销、禁用后回退、恶意/非法 DTO、超限响应、凭证脱敏。
- **集成测试**：豆瓣订阅 → 搜索 → 下载 → 转移 → 刮削 → 重命名全链路无 TMDB。
- **探索测试**：feed 注册/分页/筛选、私有 provider 权限过滤、单源失败不影响其他来源、无榜单来源不伪造 feed。

## 备选方案

### 方案 A：继续以 TMDB 为主，豆瓣只做展示层补充

改动最小，但无法满足「豆瓣独立刮削」「无 TMDB 订阅」「垂直内容命名」；一旦 TMDB 无条目即断路。否决。

### 方案 B：为每个 provider 增加一套独立字段和分支

短期直观，长期形成 provider 笛卡尔积；每接一个源都要改 Scraper、NFO、订阅、命名。否决。

### 方案 C：外部微服务统一刮削，核心只存结果

隔离性好，但引入额外部署、鉴权、缓存与一致性成本，且与现有插件框架重复。保留为未来可选部署形态，不作为本期主方案。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 跨源错误合并 | 身份闸门 + 精确 ref 优先 + 低置信度不合并 + 冲突可见 |
| 字段策略过于复杂 | 提供预设，默认 `douban_primary` / `tmdb_primary`；高级策略才暴露字段级配置 |
| provider 限流/封禁 | 独立限流、缓存、熔断、可配置代理；失败只降级 |
| 迁移期双写不一致 | 以 ref 为源、TMDBID 为派生；迁移脚本可重跑；旧读路径保留 |
| 插件安全 | manifest 声明、域名白名单、DTO 校验、无 DB 直连、凭证脱敏 |
| 现有模板失效 | 字段语义不变；未知字段在预览阶段报错；插件卸载回退默认 profile |
| 探索列表触发 N+1 详情请求 | 列表只返回列表数据；`anchor_ref` 缺失时禁用订阅，详情页按需解析 |
| 跨源映射误判 | `LINK_METHOD/LINK_CONFIDENCE/REVIEWED` 记录；低置信度进入待确认，不自动合并 |
| 性能下降 | 并行取数、快照缓存、热路径零网络、provider 并发上限 |

## 决策

采用 **Provider + Composition + NamingProfile** 架构：

1. 本地 `MediaIdentity` 作为跨源稳定身份，外部 ID 变为多值 `ProviderRef`；
2. 任何 provider 都能独立作为主源，TMDB 不再是必填；
3. 字段级合成策略支持豆瓣主、TMDB 主、单源与未来多源；
4. 刮削与 NFO 消费规范快照，不再直读 provider 原始字典；
5. 命名、解析、NFO、内容形态通过插件注册扩展，核心保持通用；
6. 迁移期保留 TMDB 兼容列与旧 API，按阶段切换。

该设计同时满足当前豆瓣/TMDB 双源需求与后续 provider 扩展，不把任何垂直内容细节带入公共核心。
