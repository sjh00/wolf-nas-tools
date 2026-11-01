# 豆瓣 vs TMDB 元数据质量调研

> 调研日期：2026-10-19
> 样本：豆瓣《肖申克的救赎》（subject `1292052`）、豆瓣剧集（分季条目，含 `episodes_count`）、
> TMDB `movie/278`、`tv/100088`（含 `season/1` 分集）。
> 代码依据：`src/app/infrastructure/external/doubanapi/`、`src/app/media/lookup/tmdb_*`。

## 1. 字段对比（实测）

| 维度 | 豆瓣（frodo API） | TMDB（v3 API） |
|---|---|---|
| 中文标题 | `title` 人工维护，质量高 | 按请求语言，存在但常不如豆瓣准确 |
| 原始标题 | `original_title` | `original_title` / `original_name` |
| 别名 | `aka` 含港台译名、民间译名 | 需另调 `translations`，按语言维度 |
| 评分 | `rating={value, count}`，中文观众样本极大（例：9.7 / 335 万） | `vote_average / vote_count`（例：8.73 / 3.1 万） |
| 简介 | `intro` 人工中文长简介，常含获奖/背景信息 | zh-CN overview 常有缺失或机翻 |
| 上映日期 | `pubdate=["2026-08-28(中国大陆)"]` 数组带地区标注，**可能是重映日期**；`release_date` 常为 null | `release_date=1994-09-23` 原始日期 + `release_dates` 按国家/分级 |
| 时长 | `durations=["142分钟"]` 字符串数组（可能多剪辑版本） | `runtime` 整数分钟 |
| 海报 | 单张 `cover_url`（webp），有 large/normal/small 尺寸 | `poster_path` 多尺寸，票数排序 |
| 背景图/Logo | **无 backdrop，无 logo**；剧照走 `photos` 端点 | backdrops / logos / stills 齐全 |
| 演职员 | 详情仅演员名列表；celebrities 端点有 `latin_name/avatar/roles` | cast（character/order/头像）+ crew（job 细分，百级） |
| 外部 ID | API 无 imdb_id（只能网页 xpath 刮，见 `webapi.py`） | `imdb_id / wikidata_id` 等 `external_ids` |
| 剧集结构 | **按季分条目**（每季独立 subject_id）；API 仅 `episodes_count` 计数 | show → seasons → episodes，分集含 `air_date/runtime/overview/still/vote` |
| 分集元数据 | API 无；**HTML 有**（分集列表页 `subject/{id}/episodes/`、分集页 `subject/{id}/episode/{n}/`），但强制 Cookie 且被 `sec.douban.com` 风控（实测 302） | API 原生完整 |
| 季数/集数 | 网页端点可刮 `季数/集数`；API 只有 `episodes_count` | `number_of_seasons / number_of_episodes` + seasons 数组 |
| 类型 | `genres` 中文标签数组 | `genres` 带 id + 按语言名称 |
| 国家/语言 | `countries` / `languages` 中文名数组 | `production_countries / spoken_languages`（ISO 结构） |
| 出品方 | 无（`vendors` 是国内流媒体播放源） | `production_companies / networks` |
| 预告 | 单个 `trailer`（中国大陆预告，含封面/时长） | `videos`（YouTube）列表 |
| 榜单 | `honor_infos`（如 Top250 #1）+ 30+ subject_collection 榜单端点 | 无榜单概念，只有 `popularity` 数值 |
| 分级 | `is_restrictive` 布尔 | `release_dates` 内含 certification |
| 播放源 | `vendors / linewatches`（国内在哪看） | `watch/providers` 需单独端点 |
| 互动指标 | `comment_count / review_count / forum_topic_count` | 无 |

## 2. 数据质量结论

### 豆瓣更强的场景

- **中文本地化**：标题、简介、别名（含港台译名）质量显著高于 TMDB 中文。
- **评分决策**：豆瓣评分与评价数更贴合中文用户；`comment_count`/`review_count` 是热度信号。
- **华语/综艺/冷门片覆盖**：国产剧、综艺条目 TMDB 经常缺失或资料不全。
- **榜单生态**：`movie_showing / movie_top250 / tv_chinese_best_weekly` 等 subject_collection 端点
  可直接映射为 ADR-025 的 `DiscoveryProvider` feed，无需爬 HTML。
- **展示速览**：`card_subtitle`（`1994 / 美国 / 剧情 犯罪 / 导演 / 主演`）可直接用于卡片副标题。

### TMDB 更强的场景

- **剧集结构**：豆瓣按季分条目；API 无分集元数据，HTML 层有分集页但 Cookie 风控，
  属于降级通道而非主链路；
- **图片体系**：backdrop/logo/多尺寸海报，豆瓣只有单海报，媒体库刮削必须用 TMDB 补图。
- **日期语义**：`release_date` 为原始上映日；豆瓣 `pubdate` 可能是地区重映日，不能直接当原始日期。
- **跨源映射**：`external_ids`（imdb/wikidata）让 identity 链接可靠；豆瓣只能靠标题+年份模糊匹配。
- **稳定性**：官方 API + 明确限流（项目配置 `tmdb_rate=40/10s`）；豆瓣 frodo 为私有接口，
  依赖内置 key/UA 伪装，存在风控与字段漂移风险（`null_rating_reason` / `localized_message`）。

## 3. 对合成策略（ADR-025）的约束

### 3.1 `douban_primary` 字段分配

```yaml
title:          douban（TMDB 兜底）
original_title: douban（TMDB 兜底）
aka/aliases:    douban + TMDB translations 并集
overview:       douban（TMDB 兜底，避免豆瓣 intro 为空）
rating:         命名空间共存 ratings.douban / ratings.tmdb，不合并
release_date:   TMDB 原始日期优先；豆瓣 pubdate 需地区过滤且排除重映日
runtime:        TMDB 整数优先；豆瓣 durations 取第一个数字兜底
poster:         TMDB 优先（多尺寸/票数），豆瓣兜底
backdrop/logo:  仅 TMDB
seasons/episodes: 仅 TMDB（动漫可由 Bangumi 补充别名/放送信息）
credits:        TMDB cast/crew 为主；豆瓣 celebrities 补中文名与头像
external_ids:   TMDB；豆瓣不提供 imdb_id（API 层）
```

### 3.2 豆瓣日期陷阱

- `pubdate` 是数组且带地区后缀（`2026-08-28(中国大陆)`），需按目标地区筛选；
- 重映/再映日期会排在前面，**不能取第一个就当年份来源**；
- `year` 字段是稳定的出品年份，年份来源用 `year` 而不是 `pubdate`；
- 日历/订阅用 `pubdate` 时要去掉地区标注并校验是否晚于 `year` 超过阈值（>3 年视为重映）。

### 3.2.1 豆瓣分集元数据（HTML 层补充）

豆瓣分集数据存在但只在 HTML 层：

```text
分集列表页: https://movie.douban.com/subject/{id}/episodes/
分集详情页: https://movie.douban.com/subject/{id}/episode/{n}/
```

分集页结构（实测《兰香如故》`36449295/episode/4/`，200 响应 31KB）：

```text
title:        "兰香如故 第4集"
字段区:        第4集 / 本集中文名 / 本集原名 / 播放时间 / 剧情简介（<span> 标签文本，可 xpath）
分集导航:      <a href="/subject/{id}/episode/{n}/"> × 47 —— 一页即可枚举全季分集
```

字段是用户贡献制，冷门分集可能「暂无，欢迎添加」（本例即空）；热门剧集通常有中文分集名与首播日期。

#### 风控与 Cookie 取证（2026-10-20 实测）

裸请求分集页流程：

```text
GET /subject/36449295/episode/4/
  → 302 https://sec.douban.com/c?r=<目标>&_s=<hex>&a=1
  → 挑战页内嵌 PoW：求解 SHA-512(cha + nonce) 前 4 位 hex == "0000"
  → POST /c (tok, cha, sol=nonce, red)
  → 302 回目标页，Set-Cookie: dbsawcv1（HttpOnly，Max-Age=120）
  → GET 目标页 200
```

Cookie 来源取证：

| Cookie | 生成方 | 证据 |
|---|---|---|
| `bid` | **服务端** Set-Cookie | 首次任意响应即下发，1 年有效，匿名浏览器 ID |
| `ll` | **服务端** | 按 IP 地理位置设置的城市代码（遗留 cookie，挑战流程未出现，非必需） |
| `dbsawcv1` | **服务端** Set-Cookie | PoW 验证通过后由 `sec.douban.com` 下发；HttpOnly、Secure、**TTL 仅 120 秒**；载荷为 `时间戳@哈希@...` 服务端签名 |
| `ap_v` | **本地 JS 生成** | `asset.doubanio.com/.../dui.switcher.*.js` 中 `ap_v:(o?"1":"0")+","+r` 写入；分析/开关用途，与风控无关 |

要点：

- 本地 JS 只计算 **PoW 的 nonce**，cookie 本体由服务端签发；不能伪造 `dbsawcv1`，
  但可以离线复现 PoW 求解（SHA-512(cha+nonce)，4 位前导零，实测 ~1 万次迭代 / 0.01s）。
- `dbsawcv1` TTL 120s，意味着 HTML 层访问需要**挑战求解器常驻**：
  每次风控触发时走一遍「GET → 解析 tok/cha → 求 nonce → POST /c → 重试」。
- 风控触发与 IP/频率/路径相关；带上有效登录 Cookie 可显著降低触发率（`DoubanWeb` 的 `CookieAuth`）。

参考求解实现（已实测通过）：

```python
def solve_douban_pow(cha: str, difficulty: int = 4) -> int:
    import hashlib
    nonce = 0
    target = "0" * difficulty
    while True:
        nonce += 1
        if hashlib.sha512((cha + str(nonce)).encode()).hexdigest().startswith(target):
            return nonce
```

### 3.3 剧集身份映射

- 豆瓣剧集条目 ≈ TMDB `show + season`，`MEDIA_EXTERNAL_REF.SCOPE` 记录 `season=N`；
- 一个 TMDB show 可能对应多个豆瓣 subject（每季一条）；
- 豆瓣订阅的「季」概念天然对齐豆瓣条目，但 NFO/媒体服务器需要 TMDB show 结构；
- `refresh` 时禁止再把豆瓣订阅单向转成 TMDB（ADR-025 已决策），改为双向 ref 并存。

### 3.4 请求治理

- 豆瓣 frodo 接口保留随机休眠（现 1-5s）与长 TTL 缓存；并发默认 1-2；
- `null_rating_reason` 非空表示「暂无评分」，与「查询失败」区分；
- `localized_message` 表示风控/错误，映射为 `ProviderUnavailable`，不缓存空结果；
- 网页端点（imdb_id、季集数）需要 Cookie，作为可选增强而非主链路。

## 4. 能力声明建议（ProviderDescriptor）

| provider | capabilities | 说明 |
|---|---|---|
| `tmdb` | search/detail/ids/seasons/episodes/credits/images/release_dates（全部 api tier） | 全能力 |
| `douban` | search/detail/credits/discovery（api tier）+ episodes/images-extra/imdb（html tier，cookie 风控） | 剧集分集与 imdb 走 HTML 降级通道 |
| `bangumi` | search/detail/relations/calendar | 动漫放送与别名 |

豆瓣 `images` 能力标记为 `limited`（仅海报/剧照，无 backdrop/logo），
合成器据此强制 TMDB 兜底图片字段。豆瓣 `EPISODES` 能力存在但 tier=html，
合成时优先级始终低于 TMDB 的 api tier 实现。
