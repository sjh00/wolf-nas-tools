# ADR-024: 媒体库批量重命名（命名规则变更后处理存量文件）

> 状态：Draft（2026-10-18 评审后修订，未实施）

## 背景

命名规则（`movie_name_format` / `tv_name_format`，`src/app/core/settings.py`）只在**转移入库时**用于计算目标路径。用户修改规则后：

- **新入库**的文件按新规则命名；
- **已入库**的存量文件保持旧名，无任何自动迁移。

这导致库里命名风格不一致，且无法通过现有能力批量纠正。需要一种**安全、离线、可预览、可恢复**的方式对存量文件按当前规则重命名。

已核对的关键事实：

- 命名计算复用 `TransferPathResolver.get_format_dict`（`src/app/services/transfer/path_resolver.py:375`）+ `name_format`，与转移流程保持一致。
- `TRANSFER_HISTORY`（`src/app/db/models/transfer.py:21`）保存 `TYPE/TITLE/YEAR/TMDBID/SEASON_EPISODE/CATEGORY/DEST/DEST_PATH/DEST_FILENAME/MODE/DST_BACKEND`，但它是**转移日志**，不是媒体库元数据表；`MODE` 被重新识别流程当作 `operation` 使用（`src/app/services/sync_service.py:471`），统计接口按 `TYPE/DATE` 聚合（`src/app/db/repositories/transfer_repository.py:296`、`:310`）。
- 仓库中**不存在** `delete_transfer_history_by_dest`；现有更新接口只有 `update_transfer_history_date`（`transfer_repository.py:50`），`insert_transfer_history` 在 `in_path` 为空时直接返回（`:78`）。
- 转移时生成 NFO 是**有条件**的：`media.nfo_poster` 未开启时不会生成（`src/app/media/scraper/__init__.py:61`、`:207`）；命名包括 `movie.nfo`、`<base>.nfo`、`tvshow.nfo`、`season.nfo`，并非全部与视频同基名。
- 默认命名格式包含 `{part}`（`src/app/core/constants.py:103-106`、`src/app/core/settings.py:162-163`），而 `part` 来自手动转移参数（`src/app/media/service.py:886`、`:1061`），`TRANSFER_HISTORY` 未存储。

## 决策

新增**媒体库批量重命名**能力，采用「**预览计划 → 确认执行 → 后台任务 → 可恢复日志**」四段式流程，遵循以下原则：

1. **离线优先**：预览默认不访问 TMDB、不重新识别；使用历史、下载历史、NFO、文件名和本地媒体服务器元数据。联网补全/重新识别必须显式开启，并在**计划阶段**完成、落快照；执行阶段不再发起新的联网请求。
2. **幂等**：同一规则重复执行必须不产生任何变更；禁止把「当前文件名」当作 `original_name` / `rev_name` / `part` 等身份字段的来源，避免越改越长。
3. **元数据来源分级**：有历史时 `TRANSFER_HISTORY` → `SOURCE_FILENAME`（原始下载名重解析）→ NFO；无历史时 `LIBRARY_MEDIA_METADATA` → `DOWNLOAD_HISTORY` → NFO → 媒体服务器 → 文件名解析/在线识别 → 人工映射。`DEST_FILENAME` **不作为身份/剧情字段的来源**；仅在无源名、无 NFO 时作为发布信息（分辨率/编码/片源/发布组等）的最后兜底，并标注来源。
4. **同根、同后端、保留分类**：锁定原 `DEST` 根目录与 `DST_BACKEND`，不跨根、不换后端；默认保留当前分类/「精选」目录，不因改名重新分类。
5. **不改写转移历史语义**：不补插伪转移记录，不修改 `MODE`。命中历史时只更新 `DEST_PATH` / `DEST_FILENAME`；未命中时只写独立的 rename journal。
6. **统一文件操作入口**：所有移动/改名通过 `StorageBackend` 完成，支持本地/远程后端；不直接 `shutil.move`，不复用会写黑名单的 `TransferEngine.transfer()`。
7. **安全闭环**：计划快照、批内冲突检测、路径白名单、单条失败隔离、持久化回滚日志、崩溃恢复、缓存失效。
8. **附属资产与目录级资产分开处理**：同基名字幕/音轨跟随改名；`movie.nfo`/`tvshow.nfo`/`season.nfo`/海报等目录级资产按目录整体移动，不按单文件误改。
9. **并发协调**：批量任务与转移/同步共享目标级锁；批量任务自身全局单飞。
10. **媒体服务器刷新尽力而为**：Plex 支持按路径刷新，Emby 按媒体库/剧集刷新，Jellyfin/FnOS 只能整库刷新；批量结束后合并刷新旧/新路径，并如实提示。

### 非目标（v1）

- 不默认重新识别、不默认联网补全 TMDB 元数据。
- 不跨媒体库根目录迁移，不切换存储后端。
- 不处理多后端镜像副本；只处理扫描到的主副本，不保证镜像副本同步改名（见「风险」）。
- 不自动重新分类；默认保留当前分类/精选目录。
- 不为无历史文件伪造 `TRANSFER_HISTORY` 记录。
- 不提供「从旧文件名截取联网占位符原片段」模式；该方案不可靠，留待后续评估。

## 详细设计

### 1. 术语与操作范围

批量重命名实际是「**按当前规则重新布局 + 改名**」，可能同时改变目录层级和文件名。提供 `layout_mode`：

- `full`（默认）：按当前目录/季/文件格式重算完整相对路径。
- `filename_only`：只重算文件名，保持当前目录不变；适合只想统一文件名的用户。

预览必须明确展示每个条目的「旧路径 → 新路径」，避免用户误以为只改文件名。

### 2. 元数据来源与可恢复性

#### 2.1 来源优先级

**A. 有 `TRANSFER_HISTORY`（按 `DEST_PATH + DEST_FILENAME` 精确命中）**

1. **`TRANSFER_HISTORY`**：以历史字段为准。同一路径命中多条时，取最新一条作为元数据来源；执行时按旧路径批量更新全部命中记录，避免重复记录继续指向旧路径。
2. **`SOURCE_FILENAME` 重解析**：若含路径只取 basename，用 `meta_info()`（`MediaInfo`）解析原始下载名，补充 `resource_type` / `resource_effect` / `resource_pix` / `video_encode` / `audio_encode` / `resource_team` / `customization` 等发布信息。
3. **NFO**：补充历史中缺失的 `original_title` / `imdbid` / `episode_title` 等。
4. **当前文件名（仅发布信息）**：无源名、无 NFO 时，仅用于补齐分辨率/编码/片源/发布组等发布信息，不用于身份、标题、年份、季集、TMDBID。
5. **仍缺失**：身份字段缺失则跳过；联网字段在未开启联网时跳过。

**B. 无 `TRANSFER_HISTORY`（库内已有，但不在转移历史）**

这类文件必须能处理，否则「媒体库目录有、数据库没有」的存量文件永远无法整理。按以下顺序兜底：

1. **`LIBRARY_MEDIA_METADATA`**：人工确认（`IS_MANUAL=1`）的映射优先；自动缓存仅在高置信度且路径仍存在时复用，否则按下列来源重新解析。
2. **`DOWNLOAD_HISTORY`**：按 `SAVE_PATH` 精确匹配；不中时按 `TORRENT`（原始下载名）/`TITLE`+`YEAR`+`TYPE` 唯一匹配。可取 `TMDBID`、`SE`、`TORRENT` 作为 `SOURCE_FILENAME` 的替代。
3. **NFO**：同 2.3。
4. **媒体服务器**：按文件路径向已配置的 Emby/Jellyfin/Plex 查询条目元数据；电影取条目 TMDB ID，剧集取所属 Series 的 TMDB ID + 文件名/NFO 的季集。
5. **文件名解析**：解析标题/年份/季集/发布信息；识别文件名中的 `tmdb-12345` / `tmdbid=12345` 等 TMDB ID 标记。
6. **在线识别**（`reidentify_no_metadata=true`）：用文件名解析结果走 `MediaService`/TMDB 识别。
7. **人工映射**：以上都无法确定时，预览标记 `needs_metadata`，用户在界面选择/输入 TMDB ID 和季集，写入 `LIBRARY_MEDIA_METADATA` 后重新生成计划。

解析结果先写入计划条目的 `METADATA_SNAPSHOT`；只有执行成功后才 upsert 到 `LIBRARY_MEDIA_METADATA`，避免预览阶段写入未确认或低置信度缓存。详细规则见 2.4。

#### 2.2 可恢复性矩阵

| 占位符 | 有历史时的来源 | 无历史时的来源 | 说明 |
|---|---|---|---|
| `title` / `year` / `tmdbid` / `media_type` | 历史 | `LIBRARY_MEDIA_METADATA` / `DOWNLOAD_HISTORY` / NFO（电影用 `movie.nfo`，剧集用 `tvshow.nfo`）/ 媒体服务器（剧集用 Series TMDB ID）/ 文件名+在线识别 / 人工映射 | 无历史时必须至少确定 `title`+`type`；规则引用 `{year}`/`{tmdbid}` 时对应字段缺失则跳过；**集 NFO 的 tmdbid 是单集 ID，不能当剧集 ID** |
| `category` | 当前路径 / 历史 | 当前路径 | 默认保留当前分类或「精选」；不按历史 `CATEGORY` 强制重分类 |
| `season` / `episode` / `season_episode` | 历史 `SEASON_EPISODE` | NFO / 媒体服务器 / 文件名 / `DOWNLOAD_HISTORY.SE` | 历史存在时以历史为准；不从当前文件名重新解析，避免动漫绝对集号/多集文件被改错。无历史时才由上述来源解析 |
| `name` | `TITLE` 映射 | 同左 | `TITLE` 赋给 `cn_name` 或 `en_name` 后再走 `get_name()`；是**确定性近似**，不保证等于转移时的原值 |
| `original_name` / `rev_name` | `SOURCE_FILENAME` | `DOWNLOAD_HISTORY.TORRENT` | 只从原始下载名重解析；两者都没有时**不可恢复**，规则引用则跳过 |
| `part` | 原始下载名启发式 / 人工确认 | `DOWNLOAD_HISTORY.TORRENT` 启发式 / 人工确认 | 历史未存，`meta_info` 也不产出 `part`；只有原下载名含明确 `Part 1`/`CD1`/`Disc 1` 等标记时才可启发式提取。不可从 `DEST_FILENAME` 推导；无法确认且旧名疑似含分集标识时跳过，否则按空处理 |
| `edition` / `videoFormat` / `source` / `videoCodec` / `audioCodec` / `releaseGroup` / `customization` / `effect` | `SOURCE_FILENAME` → 当前文件名兜底 | `DOWNLOAD_HISTORY.TORRENT` → 当前文件名兜底 | 优先从原始下载名重解析；无源名时允许从当前文件名做**发布信息**兜底；仍缺失按空处理并在预览标注。不得据此覆盖标题/年份/季集/TMDBID |
| `original_title` | NFO / TMDB | NFO / 媒体服务器 / TMDB | NFO 的 `originaltitle`、媒体服务器条目的 `originalTitle` 可用；否则需联网 |
| `imdbid` | NFO / TMDB | NFO / 媒体服务器 / TMDB | NFO 的 `imdbid` / `uniqueid[@type="imdb"]`、媒体服务器 `ProviderIds.Imdb` 可用；否则需联网 |
| `episode_title` | NFO / TMDB | NFO / 媒体服务器 / TMDB | 集 NFO 或媒体服务器的 episode title 可用；否则需联网 |
| `en_title` | TMDB | TMDB | 媒体服务器的 `originalTitle` 不一定是英文标题；离线不可算 |
| `studio` / `networks` / `vote_average` | — | — | **不是合法占位符**，`name_format.validate()` 会拒绝 |

补充约束：

- 剧集条目必须能确定季号和集号；无法确定时进入 `needs_metadata`，不能依赖 `MediaInfo` 的默认 `S01`。
- `episode` 的补零位数依赖 `MediaInfo.get_episode_bit()`（`src/app/media/models.py:212`）和 `tmdb_info` 的季集数。离线只能用 `begin_episode` / `end_episode`；超过 99 集时可能无法完全复现转移时的位数，预览需标注该限制。
- 多集文件历史值为 `S01 E01-E05`（`get_season_episode_string`，`models.py:267`），文件名格式可能是 `S01E01E05`（`get_episode_items`，`models.py:240`）；解析时必须同时兼容两种表达，并兼容季范围（如 `S01-S02`）。
- `name` 与 `TITLE` 的映射写入 rename item 的 `metadata_source`，便于审计；它不是原值的精确复现。

#### 2.3 NFO 解析

- **后端感知**：本地用 `defusedxml`；远程后端先通过 `StorageBackend.read_stream` 读取，再交给 `defusedxml` 解析。禁止直接对不可信 NFO 使用默认 lxml 实体解析（XXE/实体膨胀）。
- **查找顺序**（不是「命中一个就停」，而是合并字段；身份字段优先级更高）：
  - 电影：`<dir>/movie.nfo` → `<dir>/<base>.nfo`；
  - 剧集：`<dir>/<base>.nfo` → `<dir>/season.nfo` → `<dir>/tvshow.nfo` → `<parent>/tvshow.nfo`；
  - 若 `<base>.nfo` 不存在，可在同目录扫描其他 `.nfo`（排除 `movie.nfo`/`tvshow.nfo`/`season.nfo`），仅当其 `season/episode` 与文件名解析结果一致且唯一时采用。
- **字段合并规则**：
  - 电影：`movie.nfo` / `<base>.nfo` 提供 title/year/tmdbid/imdbid/originaltitle；
  - 剧集：`tvshow.nfo` 提供**剧集级** title/year/tmdbid/imdbid；`episodedetails` 提供 `episode_title`/season/episode；`season.nfo` 只提供季号/季标题/季播出年，不得把 “Season 1” 当作剧集标题、剧集年份或 TMDB ID；
  - **`episodedetails.tmdbid` 是单集 TMDB ID，不是剧集 TMDB ID**，禁止写入 `media.tmdb_id`；剧集 TMDB ID 只能来自 `tvshow.nfo`、媒体服务器 Series 条目或下载历史。只有集 NFO 而无剧集 TMDB ID 时，`{tmdbid}` 相关能力和在线补全跳过；
  - `episodedetails.title` 只写入 `episode_title`，不得覆盖剧集 `title`；`tvshow.nfo` 的 `season=-1`/`episode=-1` 是占位值，不参与季集解析；
  - 同一字段冲突时，`movie.nfo`/`tvshow.nfo` 的身份字段优先，剧集 NFO 的 episode 字段优先。
- **有效性**：至少包含一个可用身份字段（`title`/`tmdbid`），或剧集包含 `season`+`episode`；`season.nfo` 的 title/year **不计入身份字段**，只用于提供 `seasonnumber`。解析失败、字段为空、文件过大或 XML 异常视为无效。
- **类型推断**：NFO 无法区分 `tv` 与 `anime`，必须按当前文件所在媒体库根配置推断；无法确定时跳过。
- **多集文件**：NFO 生成处对 `int(get_episode_seq())` 可能失败（`src/app/media/scraper/__init__.py:314`），多集文件可能没有 NFO；此时回退到 `SOURCE_FILENAME` 解析或跳过。
- **陈旧 NFO**：优先比较 `tmdbid`、`season`、`episode`、`year`；标题语言不同不算冲突（例如中文 NFO + 英文文件名）。只有 ID/季集/年份明显矛盾时才标记「NFO 可能过期」，默认跳过并等待人工确认。

#### 2.4 无历史文件（库内已有但不在 `TRANSFER_HISTORY`）

这是常见场景：手工放入媒体库、转移历史被清理、从旧系统迁移、旧版本入库等。处理目标不是简单跳过，而是「尽量自动解析 + 明确人工补录」：

1. **`LIBRARY_MEDIA_METADATA` 缓存**：人工确认的映射优先；自动缓存仅在高置信度且路径仍存在时复用，否则继续下面的来源。
2. **`DOWNLOAD_HISTORY` 下载历史**（本项目下载的文件通常有记录）：
   - 先按 `SAVE_PATH == 当前文件路径` 或 `== 父目录` 精确匹配；
   - 不中时按 `TORRENT`（原始下载名）的 basename 与当前文件 basename 匹配；
   - 再不中时按文件名解析出的 `TITLE + YEAR + TYPE` 匹配；
   - 只有**唯一命中**才采用；多条记录且无法用年份/类型/季集消歧时视为不可用；
   - 可取 `TMDBID`、`SE`（季集）和 `TITLE/YEAR/TYPE`；`TORRENT` 仅当其 basename 与当前文件 basename 匹配（或能确认是同一单文件）时才作为 `SOURCE_FILENAME` 的替代，季包/目录名不能当作单集原始名。
3. **NFO**：按 2.3 解析；电影用 `movie.nfo` 的 `title/year/tmdbid`，剧集用 `tvshow.nfo` 的剧集级 `title/year/tmdbid` 加集 NFO 的 `season/episode/episode_title`，是库内文件最可靠的离线来源之一。
4. **媒体服务器元数据**（`use_mediaserver_metadata=true`，默认）：
   - 对已配置的 Emby/Jellyfin/Plex 建立一次「文件路径 → 条目元数据」索引，避免逐文件请求；
   - Plex：遍历 section 条目的 `locations` 匹配路径；电影取条目 `tmdbid`，剧集取所属 `show` 的 guids（Series TMDB ID）+ 条目 `season/episode`，不得使用单集 guids；
   - Jellyfin/Emby：按路径递归查询 `Movie/Episode` 条目；电影取条目的 `ProviderIds.Tmdb`/`ProviderIds.Imdb`，剧集必须取所属 Series 的 `ProviderIds`，不能使用单集 ProviderIds；
   - **只按路径匹配，不按标题猜测**；路径不匹配时视为无结果；同一路径匹配到多个条目且 TMDB ID 不一致时视为不唯一，进入 `needs_metadata`。媒体服务器不可用/超时只告警，不阻断计划。
5. **文件名解析**：
   - 用 `meta_info()` 解析标题/年份/季集/发布信息；
   - 额外识别常见 TMDB ID 标记：`tmdb-12345`、`tmdbid=12345`、`{tmdb-12345}` 等（正则提取）；
   - 类型由媒体库根配置推断；无法确定时跳过。
6. **在线识别**（`reidentify_no_metadata=true`）：用文件名解析结果走 `MediaService`/TMDB 识别；必须显式开启。
7. **人工映射**：以上都无法确定时，预览标记 `needs_metadata`；用户在界面搜索 TMDB 或输入 TMDB ID/季集，写入 `LIBRARY_MEDIA_METADATA`，然后重新生成计划。人工映射是该文件的长期元数据来源。

两个联网开关的职责不同：

- `allow_online_metadata=true`：只对**已有 TMDBID** 的条目补全 `en_title` / `episode_title` / `original_title` / `imdbid` / 季集数等信息，不负责识别未知文件；
- `reidentify_no_metadata=true`：对无 TMDBID 的文件用文件名识别，成功后也会补全上述字段；
- 两者都在**计划阶段**执行并写入计划快照；执行阶段不重复联网。

置信度与持久化：

- `LIBRARY_MEDIA_METADATA`（人工/缓存）、NFO、媒体服务器精确路径、`DOWNLOAD_HISTORY.SAVE_PATH` 精确匹配：高置信度；
- `DOWNLOAD_HISTORY.TORRENT`/`TITLE+YEAR+TYPE` 唯一匹配、文件名+在线识别：中置信度；
- 自动缓存复用前校验路径存在且 `FILE_SIZE`/`FILE_MTIME` 一致（远程后端可跳过 mtime）；不一致则缓存失效并重新解析；人工映射不因文件大小变化自动失效；
- 匹配不唯一或字段冲突：不采用，进入 `needs_metadata`；
- 解析结果先写入计划条目快照；**执行成功后**才 upsert 到 `LIBRARY_MEDIA_METADATA`，后续计划可离线复用。人工补录则立即 upsert；
- **人工映射（`IS_MANUAL=1`）不得被自动解析覆盖**，只能由用户显式重新映射；自动 upsert 也不得把已有 `high` 置信度降级为 `medium`；
- 无 `SOURCE_FILENAME` / `DOWNLOAD_HISTORY.TORRENT` 时，`original_name`/`rev_name`/`part` 仍不可恢复；规则引用这些字段的条目跳过。

**结论**：「媒体库目录有、数据库没有」不是死路；默认至少可以通过 NFO、下载历史、媒体服务器或文件名解析处理。只有完全无法识别且用户也不补录的文件才会被跳过。

### 3. 路径计算

- 在任务开始时创建**独立的 `TransferPathResolver` 快照**（`from_settings` 后只读），不要复用 DI 中的共享实例。共享实例会被转移任务按 TTL `refresh()`（`path_resolver.py:138`、`filetransfer_service.py:377`），导致同一批次前后规则不一致。
- 启动前对 `movie_name_format` / `tv_name_format` 及拆分后的目录/季/文件格式调用 `name_format.validate()`；未知字段直接拒绝执行。
- 用 `name_format.parse_fields()` 识别规则引用的字段，结合第 2.2 节判断是否可离线恢复。处理策略：
  - **身份字段** `original_name` / `rev_name` 无法恢复且被引用 → 跳过，预览标注 `unrecoverable_field:xxx`；
  - **`part`** 无法恢复且旧名疑似含分集标识 → 跳过；否则按空处理；
  - **发布信息字段**（分辨率/编码/片源/发布组等）无法恢复 → 按空处理，预览标注 `missing_release_field:xxx`；
  - **联网字段** 未开启联网 → 跳过，预览标注 `requires_online:xxx`。
  - 可选片段 `{field:...}` 语法可让字段为空时整段消失；即使使用可选片段，也必须在预览中标注该字段缺失。
- **禁止使用 `DEST_FILENAME` 作为 `original_name` / `rev_name` / `part` 的来源**；这三类字段只能来自 `SOURCE_FILENAME` 或人工确认。
- `get_format_dict` 通过一个**只读元数据适配器**提供 `episode_title` / `en_title`（以及联网补全结果）；适配器只读计划快照，不发起网络请求。`get_format_dict` 自身仍复用现有实现，避免与转移流程产生两套命名逻辑。
- 新文件扩展名沿用旧文件扩展名；`get_movie_dest_path` / `get_tv_dest_path` 返回的是不含扩展名的文件名。
- **保留分类/精选**（默认开启）：
  - 从当前相对路径识别首段是否为 `RMT_FAVTYPE`（可配置的「精选」）或已配置分类；
  - 新路径保留该分类前缀，再拼接当前规则生成的子目录；
  - `reorganize_category=true` 时改为按历史 `CATEGORY` 重新分类，并在预览中高亮；该选项与 `preserve_current_category` 互斥，`reorganize_category` 优先。
- **目标根目录（无历史时）**：按当前配置的媒体库根做最长前缀匹配，并解析对应 `DST_BACKEND`；匹配不到、根已从配置删除或后端不可用时跳过。
- **历史 `DST_BACKEND` 为空时**：按 `DEST` 根匹配当前配置的媒体库根/后端；仍无法唯一确定时跳过，不能默认按本地后端处理。
- **安全校验**：
  - 目标路径必须位于原根目录内，且属于配置的媒体库根/历史 `DEST` 白名单；
  - 拒绝空文件名、`..`、绝对路径、Windows 保留名、尾部空格/点、超长路径；
  - 目标目录/文件不得覆盖已有内容；
  - 大小写不敏感文件系统上，本地后端用 `samefile`、远程后端用后端规范化路径判断「仅大小写变化」，不能直接判定为冲突；
  - 目标路径按后端大小写规则规范化后再做批内去重，避免同一目标出现大小写不同的两条计划。
- **幂等判断**：规范化后新旧路径相同则记为 `unchanged`，不执行任何文件操作。

### 4. 数据模型与历史同步

新增独立表，不复用 `TRANSFER_HISTORY` 作为任务日志：

#### `LIBRARY_RENAME_JOB`

- `ID`、`PLAN_ID`（UUID）、`STATUS`（`planned/running/cancelled/completed/failed/interrupted`）
- `SCOPE`（JSON：媒体类型、根目录、`layout_mode`、是否允许联网等）
- `RULE_SNAPSHOT`（JSON：生成计划时的目录/季/文件格式、分类开关、媒体库根与后端映射）
- `CREATED_BY`、`CREATED_AT`、`STARTED_AT`、`FINISHED_AT`
- 统计字段：`TOTAL`、`CHANGED`、`UNCHANGED`、`SKIPPED`、`CONFLICT`、`NEEDS_METADATA`、`FAILED`

#### `LIBRARY_RENAME_ITEM`

- `ID`、`JOB_ID`
- `BACKEND_ID`、`ROOT`
- `OLD_PATH`、`NEW_PATH`、`OLD_PATH_HASH`（按规范化旧路径计算 sha256，用于唯一约束与长路径索引）
- `OLD_SIZE`、`OLD_MTIME`（用于执行前一致性校验，远程后端可为空）
- `METADATA_SOURCE`（`history/source_name/download_history/nfo/mediaserver/filename/filename_fallback/reidentify/online/manual/title_fallback`）
- `METADATA_SNAPSHOT`（JSON，保存本次使用的标题/年份/季集/TMDBID/发布字段/`SOURCE_FILENAME`，以及影响命名的 `tmdb_info` 最小字段（如季集数），便于审计与执行阶段复用）
- `ACTION`（`rename/unchanged/skip/conflict/needs_metadata`）、`STATUS`（`planned/running/done/failed/rolled_back/manual_intervention`）
- `DIRECTORY_MOVE_ID`（目录整体移动时共享的事务标识）
- `REASON`、`ERROR`、`ROLLBACK_STATUS`
- 唯一约束：`(JOB_ID, OLD_PATH_HASH)`（长路径用哈希列，避免 MySQL 唯一索引超键长）

#### `LIBRARY_MEDIA_METADATA`

用于持久化「库内文件 → 元数据」映射，解决无历史文件以及跨计划复用问题：

- `ID`、`BACKEND_ID`、`PATH`、`PATH_HASH`（按规范化路径计算 sha256，唯一索引 `(BACKEND_ID, PATH_HASH)`）
- `TYPE`、`TITLE`、`YEAR`、`TMDBID`、`SEASON`、`EPISODE`（季/集允许范围字符串，如 `1`、`1-5`）、`SEASON_EPISODE_COUNT`（用于还原 `get_episode_bit()` 所需的总集数，可为空）；`TMDBID` 对剧集必须是 Series TMDB ID，不得存单集 ID
- `SOURCE_FILENAME`（可来自 `TRANSFER_HISTORY.SOURCE_FILENAME` 或 `DOWNLOAD_HISTORY.TORRENT`；若为路径，只保存 basename）
- `METADATA_SOURCE`（`history/download_history/nfo/mediaserver/filename/online/manual`）
- `CONFIDENCE`（`high/medium`）、`IS_MANUAL`
- `FILE_SIZE`、`FILE_MTIME`（用于判断自动缓存是否仍对应当前文件；远程后端可为空）
- `RAW`（JSON，保存解析上下文，便于审计）
- `CREATED_AT`、`UPDATED_AT`、`UPDATED_BY`

写入/更新时机：

- 计划阶段只写 `LIBRARY_RENAME_ITEM.METADATA_SNAPSHOT`，不写全局缓存；
- 改名成功（文件移动 + 历史更新完成）后 upsert，并把 `PATH` 直接写为新路径；
- 人工补录时立即 upsert 并标记 `IS_MANUAL=1`；
- 文件删除/移出媒体库时可选清理；清理失败不影响主流程。

迁移要求：

- 新增上述表及必要索引；
- 为 `TRANSFER_HISTORY` 增加 `(DEST_PATH, DEST_FILENAME)` 复合索引，避免逐文件全表扫描（现有 255 长度下满足 MySQL InnoDB 键长限制）；
- v1 不扩列：执行前拒绝 `DEST_PATH` / `DEST_FILENAME` 超过 255 的条目。后续如需支持更长路径，必须同时设计前缀索引或哈希列，不能只扩列导致索引超键长。

历史同步规则：

- 新增 repository 方法：按 `(DEST_PATH, DEST_FILENAME)` 查询历史、按 ID 批量更新 `DEST_PATH` / `DEST_FILENAME`；
- 命中历史：按旧路径查询全部命中记录并批量更新 `DEST_PATH` / `DEST_FILENAME`；默认**不修改** `DEST`、`CATEGORY`、`MODE`、`DATE`、`DST_BACKEND`。仅 `reorganize_category=true` 且分类实际变化时更新 `CATEGORY`；
- 未命中历史：**不插入** `TRANSFER_HISTORY`，执行成功后写 `LIBRARY_MEDIA_METADATA`（`PATH` 直接为新路径），计划阶段只写 `LIBRARY_RENAME_ITEM.metadata_snapshot`；
- 命中历史且执行成功：同步更新 `DEST_PATH`/`DEST_FILENAME`，并在同一事务/步骤内 upsert `LIBRARY_MEDIA_METADATA`（旧路径 → 新路径），保证下次计划可离线命中；
- `SYNC_HISTORY` 保持不动（它记录源文件路径与目标根，不记录媒体库文件名）；
- 完成后失效 `TransferHistoryService` 的 30 秒内存缓存及相关媒体库列表缓存。

### 5. 扫描与计划

- 复用 `MediaLibrary.get_library_files`（`src/app/media/scraper/media_library.py:18`）按后端递归遍历，仅处理 `RMT_MEDIAEXT` 媒体文件。
- 排除规则：隐藏目录、回收站（`#recycle`、`.Trash`）、`@eaDir`、未识别的下载临时目录、配置中排除的路径。
- 扫描结果按 `(backend_id, 规范化路径)` 去重，避免根目录嵌套/多个 scope 重叠导致同一文件被计划两次；不跟随目录符号链接，避免循环或重复。
- `scope` 必须结构化：
  - `media_types`：`movie/tv/anime`，至少一项；
  - `roots`：可选，必须是配置的媒体库根或历史 `DEST`；
  - `layout_mode`：`full/filename_only`；
  - `preserve_current_category`：默认 `true`；
  - `reorganize_category`：默认 `false`；开启后按历史 `CATEGORY` 重新分类；
  - `use_mediaserver_metadata`：默认 `true`；只查询已配置的本地 Emby/Jellyfin/Plex，按路径匹配；
  - `allow_online_metadata`：默认 `false`；
  - `reidentify_no_metadata`：默认 `false`；
  - `limit`：单次计划/单批执行上限，必须有服务端上限。
- 计划阶段完成：
  - 元数据解析：历史命中 → `LIBRARY_MEDIA_METADATA` → 无历史兜底链（2.4）；
  - 新路径计算；
  - **批内目标去重/预留**：两个源文件映射到同一目标时全部标记 `conflict`，不能先到先得；
  - 已有目标检测、目录冲突检测、路径/长度/权限预检；
  - 无法解析的条目标记 `needs_metadata`，保留在计划中供人工补录；执行时跳过，直到补录后重新生成计划；
  - 生成 `LIBRARY_RENAME_ITEM` 快照，返回 `plan_id`。
- 计划有效期默认 24 小时；执行入口必须校验计划未过期。执行阶段用 `RULE_SNAPSHOT` 重建只读 resolver，避免执行期间改配置导致预览与执行不一致。配置变更后旧计划只能查看或重新生成。

### 6. 执行、回滚与崩溃恢复

执行顺序（单条目）：

1. 读取并校验 rename item：文件仍存在、大小/mtime 与计划一致、目标仍空闲、后端仍可用；
2. 获取目标级锁；
3. 记日志状态 `running`；
4. 移动/改名视频；
5. 处理同基名字幕/音轨；
6. 更新历史（命中时）并更新 item 状态；
7. 释放锁。

文件操作约定：

- 统一通过 `StorageBackend`：同一后端优先 `move`/服务端改名；本地同分区为 rename，跨分区为 `copy2 + remove`；远程后端按其 `move` 语义执行。
- 不调用 `TransferEngine.transfer()`，避免写入 `TRANSFER_BLACKLIST`（`src/app/services/transfer_engine.py:279`）。
- 硬链接安全仅对本地后端成立：本地 rename 保持 inode；远程 `link` 会降级为 copy（`transfer_engine.py:55`），预览需标注。
- 目录移动策略：
  - 仅当一个旧目录内的**所有媒体文件**都被本计划覆盖、且 action 均为 `rename`（都映射到同一新目录）、新目录不存在时，才整体移动目录；存在 `skip`/`needs_metadata`/`conflict`、或目录内有未被 `limit`/`scope` 覆盖的媒体文件时，禁止整体移动；
  - 满足条件时，`tvshow.nfo`/`season.nfo`/海报/字幕随目录一起移动；
  - 否则逐文件移动，只移动同基名字幕/音轨，目录级共享海报/NFO 保留并告警；
  - 不按单文件重命名 `poster.jpg`、`fanart.jpg`、`seasonXX-poster.jpg` 等共享资产。
- 旧目录清理：仅在所有文件处理完成、目录为空、位于媒体库根内、且不是根/分类根/精选根时删除；失败不阻断主流程，仅告警。
- 媒体服务器刷新：收集所有条目的旧/新视频**文件路径**并去重，按各 client 需要组装（Plex 用 `file_path`，内部取父目录刷新；Emby 用 `title/year/type` 定位媒体库或剧集；Jellyfin/FnOS 退化为整库刷新）；刷新失败只告警，不回滚文件操作。

回滚：

- 每条目在移动前先写 journal；失败按逆序回滚（历史 → 元数据缓存路径 → 附属文件 → 视频 → 清理新建空目录）。
- 整体移动目录时，以目录为回滚单元：所有关联 item 共享同一 `directory_move_id`，目录搬回后统一恢复 item 状态和元数据缓存路径。
- **跨分区 copy+delete 不能通过「删除新文件」回滚**，必须把新文件搬回旧路径；搬回失败标记 `manual_intervention` 并保留 journal。
- 崩溃恢复：启动时把 `running` 状态的 job 标记为 `interrupted`；提供「继续未完成项」和「回滚已完成项」两个入口。恢复时根据 `OLD_PATH`/`NEW_PATH` 的实际存在性判断：新路径在、旧路径不在则补写历史/元数据缓存；旧路径在、新路径不在则重试移动；两者都在或都不在则标记 `manual_intervention`。未确认前不自动删除任何文件。
- 回滚只针对本 job 记录的操作；用户手工改名后的路径不自动猜测。

### 7. 并发与锁

- 批量任务全局单飞：`library:rename:job`，避免两个计划同时操作同一媒体库。
- 目标级锁：`library:target:{backend_id}:{root}:{tmdbid}:{season}`，按条目获取，TTL 覆盖单条操作；同一剧集的多集共享同一把锁。无 TMDBID 时用目标父目录的规范化哈希作为维度。
- 现有转移锁按源路径生成（`filetransfer_service.py:362`），与目标级锁不是同一 key。**实施本 ADR 时必须把转移/同步写入媒体库的路径也接入同一目标锁**；否则「避免与转移/同步同改同一目标」不成立。若暂不改造，ADR 必须降级为「仅保证批量任务内部互斥」并在预览中提示。
- 多目标锁按固定顺序获取，避免死锁。
- 不使用 DI 共享的 resolver；每个任务使用自己的规则快照。

### 8. 接口与前端

后端（建议放在媒体库域，避免与 `/api/sync/rename` 手动转移混淆）：

- `POST /api/media/library/rename/preview`：生成计划；参数为第 5 节的 `scope`；返回 `plan_id`、统计和第一页条目。
- `GET /api/media/library/rename/plans/{plan_id}/items`：分页查看计划条目。
- `POST /api/media/library/metadata`：人工补录/修正某个库内文件的元数据（`backend_id`、`path`、`type`、`tmdbid`、`season`、`episode`、`title`、`year`），写入 `LIBRARY_MEDIA_METADATA` 并标记 `IS_MANUAL=1`；必须校验路径属于媒体库根；补录后重新生成计划。
- `POST /api/media/library/rename/plans/{plan_id}/execute`：确认执行；后台任务，返回 `job_id`。
- `GET /api/media/library/rename/jobs/{job_id}`：进度与统计。
- `POST /api/media/library/rename/jobs/{job_id}/cancel`：请求取消；当前条目完成后停止。
- `POST /api/media/library/rename/jobs/{job_id}/rollback`：回滚未完成/已完成条目，需二次确认。
- 权限：`library:manage`（RBAC 现有码，见 `rbac/init/constants.py:23`）。
- 审计人取当前登录用户，写入 `LIBRARY_RENAME_JOB.CREATED_BY`；不再接受单独的 `user` 参数。
- 预览不产生任何文件操作或 `TRANSFER_HISTORY` 写入，也不写 `LIBRARY_MEDIA_METADATA`；只会写入计划和条目快照（用于确认执行），需要在文档/界面中说明。人工补录元数据是显式写操作，会立即写 `LIBRARY_MEDIA_METADATA`。
- `allow_online_metadata` / `reidentify_no_metadata` 默认 `false`。关闭时计划阶段不访问 TMDB，引用联网字段的条目跳过；媒体服务器查询由 `use_mediaserver_metadata` 单独控制。开启时**在计划阶段**完成 TMDB 查询/识别并写入 `METADATA_SNAPSHOT`，UI 必须明确提示会联网及预计耗时。执行阶段只使用快照，不再发起新的联网请求，从而保证「预览与执行一致」。
- 返回字段：`old_path`、`new_path`、`action`、`reason`、`metadata_source`、`online_fields`、`backend`、`status`、`job_id`。

前端：

- 媒体库/同步页新增「按当前命名规则重命名旧文件」。
- 第一步展示 dry-run 清单：旧/新路径、跳过的原因、冲突、不可恢复占位符、联网占位符、目录整体移动/逐文件移动。
- `needs_metadata` 条目提供「补充元数据」入口：可搜索 TMDB 或直接输入 TMDB ID/季集；保存后自动重新生成计划。
- 第二步需显式确认 `plan_id` 后执行；展示进度、失败项、回滚按钮。
- 对 `{part}`、`original_name`、`en_title` 等高风险字段做解释提示。

### 9. 多用户与权限（ADR-021）

批量重命名属**全局媒体库闸门**操作，按系统上下文执行；接口受 `library:manage` 写权限保护；不涉及用户私有数据行级过滤。操作人记录在 rename job 中用于审计，但不改变数据归属模型。`DOWNLOAD_HISTORY` 仅用于读取 TMDB/标题/季集等媒体元数据，不向接口返回用户下载记录。

### 10. 实施影响面（预估）

- 模型/迁移：新增 rename job/item 与 `LIBRARY_MEDIA_METADATA` 模型及 Alembic 迁移；`src/app/db/models/transfer.py` 增加复合索引。
- 仓储：`src/app/db/repositories/transfer_repository.py` 与领域接口 `src/app/domain/interfaces/transfer_repo.py` 增加按目标路径查询、按 ID 更新目标路径的方法；新增 `LIBRARY_MEDIA_METADATA` 仓储。
- 服务：新增媒体库重命名服务（建议 `src/app/services/transfer/library_rename_service.py`），复用 `TransferPathResolver`、`MediaLibrary`、`StorageBackend`、`name_format`；复用 `DownloadHistoryRepositoryAdapter` 和 scraper 的 NFO 读取能力。
- 媒体服务器：为 `src/app/mediaserver/client/_base.py` 及 Emby/Jellyfin/Plex 增加按路径查询条目元数据的方法（或一次性构建路径索引）。
- 接口/DI：新增媒体库路由并注册到 `src/api/main.py`；工厂装配加入 `src/app/di/builders/services_builder.py`。
- 并发改造：`src/app/services/transfer/filetransfer_service.py` 与 `src/app/services/sync_engine.py` 接入共享目标锁。
- 刷新/缓存：`src/app/mediaserver/media_server.py` 复用按路径刷新；`src/app/services/transfer_history_service.py` 增加缓存失效入口。
- 前端（独立仓库）：计划预览、`needs_metadata` 补录、执行进度、失败/回滚页面。

### 11. 测试

- **幂等**：同一规则连续预览/执行两次，第二次 `changed=0`；含 `{original_name}`、`{part}` 的规则不漂移。
- **元数据来源**：历史精确命中；`SOURCE_FILENAME` 重解析；NFO 兜底；优先级与字段不被低优先级来源覆盖。
- **无历史文件**：NFO、`DOWNLOAD_HISTORY`（路径精确/原始名匹配/标题唯一匹配）、媒体服务器路径索引、文件名+TMDB ID 标记、在线识别、人工映射各自可命中；多义匹配不采用；`needs_metadata` 可在补录后重新生成计划。
- **元数据缓存**：预览只写计划快照，不写全局缓存；执行成功后自动解析结果与人工补录写入 `LIBRARY_MEDIA_METADATA`；改名后路径更新；后续计划离线复用；缓存失效/冲突时回退到实时解析。
- **不可恢复字段**：`original_name`/`rev_name` 无源名/`TORRENT` 时跳过；`part` 疑似存在但无法恢复时跳过；联网字段离线时跳过并在预览标注。
- **NFO**：电影/剧集/`movie.nfo`/`<base>.nfo`/`tvshow.nfo`/`season.nfo`；平铺剧集目录（`Show/tvshow.nfo`）与季目录（`Show/Season 01/tvshow.nfo` 在上级）都能命中；剧集 NFO 的字段合并；集 NFO 的 `tmdbid` 不得覆盖 Series TMDB ID；仅有集 NFO 时 `{tmdbid}` 相关字段跳过；NFO 关闭、仅有 credits、XML 异常、远程 NFO、XXE/超大文件防护。
- **路径**：与当前规则一致；`filename_only`/`full`；同根约束；分类/精选保留；无历史时根前缀匹配；不换后端。
- **冲突**：目标已存在、批内两个源映射同一目标、目录已存在、仅大小写改名、Windows 保留名/长路径。
- **附属资产**：语言后缀字幕、音轨、目录级 NFO/海报；目录整体移动与逐文件移动；空目录清理安全。
- **历史**：命中时默认只更新 `DEST_PATH`/`DEST_FILENAME`，`reorganize_category` 时按实际变化更新 `CATEGORY`；未命中不插入伪记录；`MODE` 不被当作 operation；统计接口不虚增。
- **回滚/崩溃**：逐条逆序回滚；跨分区 copy+delete 回滚必须搬回；模拟进程中断后 job 标记 `interrupted`，可继续/回滚。
- **并发**：批量任务单飞；与转移/同步共享目标锁时不并发写同一目标；锁顺序无死锁。
- **dry-run**：默认预览不移动文件、不写历史、不访问 TMDB；媒体服务器查询可 mock 或通过 `use_mediaserver_metadata=false` 关闭；开启联网选项时仅计划阶段联网并落快照，执行阶段不重复联网；预览后文件变化时执行跳过并提示重新预览。
- **硬链接**：本地改名后 inode 不变、源文件仍存在；远程后端 link 降级为 copy 的行为符合预期。
- **媒体服务器刷新**：旧/新文件路径都被收集并去重；Plex 路径刷新、Emby 媒体库/剧集刷新、Jellyfin/FnOS 全库刷新被正确调用。

## 风险 / 待决

- **NFO 可用性**：NFO 依赖 `media.nfo_poster` 与刮削配置，很多库可能没有 NFO；无历史文件需要依赖下载历史/媒体服务器/文件名/人工映射。
- **下载历史匹配**：`DOWNLOAD_HISTORY.SAVE_PATH` 是下载目录而非媒体库路径，通常无法直接命中；`TORRENT`/标题匹配可能多义。只采用唯一匹配，避免把错误 TMDB ID 写进文件名。实现上应先用已索引的 `TITLE` 缩小候选，再比对 `TORRENT`，避免逐文件全表扫描。
- **媒体服务器元数据**：Jellyfin/Emby 的 episode 按路径查询、Plex 的 section 全量遍历都需要新增客户端能力；大型库的全量索引可能耗时，建议按根分页缓存并设置超时。媒体服务器内部的挂载路径与 StorageBackend 路径不一致时按路径匹配会失败，此时只能走 NFO/下载历史/文件名/人工映射。
- **人工映射依赖**：完全无法识别的文件需要用户在预览中补录 TMDB ID；补录前保持 `needs_metadata`，不会执行改名。
- **`part` 与身份字段**：`part`、`original_name`、`rev_name` 无法从当前文件名稳定恢复；本 ADR 选择「不可恢复则跳过」而不是猜测。
- **发布信息兜底**：无源名时允许从当前文件名恢复分辨率/编码/发布组等；如果旧文件名本身不含这些信息，新规则会得到空值，预览必须明确标注 `missing_release_field`。
- **联网计划成本**：开启 `allow_online_metadata` / `reidentify_no_metadata` 后，计划阶段会批量查询 TMDB，可能耗时并触发限流；必须展示进度、支持取消，且按站点/TMDB 限流配置执行。
- **超 99 集**：离线缺少 `tmdb_info` 的季集数，补零位数可能与转移时不同；预览需提示，必要时人工确认。
- **多集文件 NFO**：NFO 生成可能失败；以 `SOURCE_FILENAME` / 历史为准，NFO 仅兜底。
- **多后端镜像**：本 ADR 只改 `TRANSFER_HISTORY` 记录的主副本；镜像副本不会自动改名。后续如需支持，必须增加按媒体库根扫描所有后端并识别镜像关系的机制。
- **远程后端**：SMB/WebDAV/S3/OpenList 的 `move` 语义、原子性、TTL 与权限差异较大；跨后端/跨分区可能退化为复制+删除，需预留空间并处理失败清理。
- **媒体服务器刷新成本**：Jellyfin/FnOS 只能整库刷新，Emby 只能按媒体库/剧集刷新；大量改名会触发大范围扫描，需分批、合并刷新并允许错峰。
- **长路径**：`DEST_PATH` / `DEST_FILENAME` 为 255；v1 预检拒绝超长项。若要扩列，必须同时处理复合索引键长（前缀索引或哈希列），否则 MySQL 迁移会失败。
- **并发**：若不改造转移/同步以共享目标锁，只能保证批量任务内部互斥；ADR 实施时必须明确这一前置条件。
- **元数据缓存失效**：`LIBRARY_MEDIA_METADATA` 可能因用户替换文件、手工改名、媒体服务器重新识别而过期；计划阶段需校验路径存在性，必要时回退到实时解析，人工映射优先。
- **分类识别**：从当前路径推断分类/精选依赖目录命名约定；无法识别时按历史 `CATEGORY`，并在预览标注。
