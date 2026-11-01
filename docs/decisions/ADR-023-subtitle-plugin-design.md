# ADR-023: 字幕插件（自动下载 + 手动上传重命名）设计

## 背景

实现 Nexus Media 的字幕能力：

- 媒体「转移」完成后自动到字幕源搜索、下载并放到视频同目录侧挂（同名 + 语言后缀）；
- 支持手动上传字幕到媒体库目录并正确重命名（手动指定或按 TMDB ID 自动定位）。

插件代码托管在 `~/python/nexus-media/nexus-media-plugins/plugins/subtitle`，作为**可安装插件**分发，
不进入后端主仓库；通过插件框架安装/升级，运行时复用事件 hook、`register_api`、
ESM 前端页面、DI 注入的 `mediaserver`/`media_service` 与 manifest 声明式 Agent 工具。

当前事件与存储能力边界：

- 转移流程同时发布 `subtitle.download` 与 `media.transfer_finished`
  （`filetransfer_service.py:949-950`）。`subtitle.download` 是专门为字幕准备的事件，
  payload 含 `media_info/file/file_ext/bluray`（`events/payloads.py:178`）。
- 蓝光原盘场景 `subtitle.download.file` 可能为 `None`（`filetransfer_service.py:993`）。
- 媒体库可能位于本地、SMB、WebDAV、S3、OpenList 等后端，字幕写入必须走后端接口，
  不能假设本地 `os.path`/`open` 可直接使用。
- 媒体服务器客户端的现有查询接口主要返回标题/季集信息，不直接返回视频文件路径：
  `get_movies` 返回 `title/year`，`get_tv_episodes` 返回季集号
  （`jellyfin.py:350-355,407-412`；Plex 同理）。

## 决策

新建可安装插件 `subtitle`，只订阅 `subtitle.download` 事件自动下载字幕，
并提供手动上传/重命名页面。字幕源抽象为可插拔 `SubtitleSource`，首期实现 Assrt，
Assrt、Thunder CID 与 Zimuku（字幕库，验证码）三路字幕源。

关键设计：

1. **事件触发（按类型分流）**：manifest `backend.hooks` 订阅
   `subtitle.download` 与 `media.transfer_finished`。
   - 普通文件只处理 `subtitle.download`；
   - 蓝光原盘 `subtitle.download.file` 为空，改由 `media.transfer_finished` 的
     `target_path`（目录）触发；
   - 两者按事件/路径类型分流，避免同一文件重复下载。
   `on_hook` 只做轻量参数整理，随后把任务提交到插件自己的线程池。
   - 蓝光目录：在 `BDMV/STREAM` 中选最大 `.m2ts` 作为主视频，再检测/下载。
2. **源适配层**：`SubtitleSource` 协议（`search`/`download`），`AssrtSource` 先落地，
   `ThunderSource`（CID 首尾分块哈希 + 名称搜索）、`ZimukuSource`（网页 + 验证码）
   与 OpenSubtitles/SubDL 后续扩展。
3. **存储后端**：插件不直接使用本地文件 API 操作媒体库。所有存在性检查、读取、
   写入、移动、目录遍历都通过 `StorageBackend`；后端由媒体库根目录配置解析。
   本地后端可以使用 `os` 实现原子替换，远程后端使用其 `write_stream`/`move` 能力。
4. **匹配打分**：标题归一化相似度 + 年份差 + 季集精确 + 语言 + 格式优先级，低于
   `min_score` 丢弃；下载前校验内容（非空/非 HTML/含字幕语法），统一转 UTF-8。
5. **手动与识别重命名**：前端 ESM 页面走 `register_api`（POST 需 `plugin:manage`），
   支持「手动指定目标」与「按 TMDB ID / 文件名自动定位」；同时支持对已有字幕做
   「识别语言/字幕标记 → 预览 → 重命名」，以及用户逐条手动指定语言/标记后重命名。
6. **多语言、多字幕命名**：一个视频可以有多条字幕（不同语言、强制、SDH、双语等）。
   语言使用 BCP-47 规范（`zh-Hans`/`zh-Hant`/`en`/`ja`/`mul`/`und`），
   字幕标记使用 `forced`/`sdh`/`cc`/`commentary` 等；输出风格支持
   `nexus`（`.chi.zh-cn/.zh-tw/.eng/.und`，兼容存量库）、`bcp47`（`.zh-Hans/.zh-Hant/.en`）
   与 `iso639`（`.zh/.en`）。命名规则抽到共享 `subtitle_naming` 工具，
   转移引擎与插件共用，禁止插件内复制第二套映射。
7. **安全**：落盘路径白名单（`library_roots`/视频所在目录）防目录穿越；
   压缩包解压拒绝绝对路径、`..`、符号链接、超限条目/压缩比；Token 日志脱敏。
8. **已有中文字幕检测**：下载前先检查外挂字幕、容器内软字幕和硬字幕；
   命中中文则跳过，避免重复下载。硬字幕使用文件名特征或可选抽帧 OCR，
   默认只启用文件名特征。
9. **全量补字幕**：支持扫描配置的媒体库根，逐视频检测并按语言下载；
   后台 job、进度、取消、dry-run，避免一次性同步请求阻塞。
10. **定时全量扫描**：支持 cron 定时触发全量补字幕；同一时间只允许一个
    全量 job，避免重复扫描和请求配额竞争。
11. **多用户（ADR-021）**：字幕落库属全局闸门，后台任务按系统上下文；
   插件不绕过 repository 读写用户数据。

### v1 非目标

- 不做跨媒体服务器/跨后端路径自动映射；媒体服务器路径无法对应后端时回退手动选择。
- 不自动覆盖已有字幕；默认 `skip`。

## 插件仓库与目录结构

插件源码放在独立仓库 `~/python/nexus-media/nexus-media-plugins/plugins/subtitle`：

```
nexus-media-plugins/
├── tools/build_catalog.py   # 市场仓库统一打包/校验 CLI
├── tests/                   # 插件测试（不打包进 zip）
├── dist/                    # 生成的 zip
└── plugins/subtitle/
    ├── manifest.json        # hooks / frontend.routes+settings / backend.tools
    ├── frontend/index.mjs   # 设置页 + 上传/重命名页（ESM，host 注入）
    ├── assets/icon.png
    ├── backend/
    │   ├── plugin.py        # SubtitlePlugin：on_hook / register_api / 线程池/agent_tool
    │   ├── config.py        # 默认配置与校验
    │   ├── models.py        # Candidate/SearchQuery/PlaceResult/RenameRule/SyncAdjustment
    │   ├── matcher.py       # 归一化/打分/去重排序
    │   ├── placer.py        # 路径推导/命名/后缀/覆盖/白名单（StorageBackend）
    │   ├── media_locator.py # TMDB ID → 媒体库视频路径（mediasync/path_resolver）
    │   ├── media_match.py   # 手动上传：字幕文件名/目录 → 视频候选
    │   ├── store.py         # 数据目录 JSON（历史/指纹缓存，原子写+分布式锁）
    │   └── sources/
    │       ├── base.py      # SubtitleSource 协议
    │       ├── assrt.py     # Assrt 搜索/下载/解压(zip|rar)
    │       ├── thunder.py   # Thunder CID + 名称搜索
    │       └── zimuku.py    # Zimuku 网页搜索 + 云锁验证码
    ├── pyproject.toml       # 插件独立开发依赖（可选）
```

安装与升级：

- 在插件市场仓库根目录执行 `python3 tools/build_catalog.py .`，生成
  `dist/subtitle-<version>.zip`、`plugins/subtitle/detail.json` 与 `catalog.json`
  （zip 根目录必须含 `manifest.json`）。
- 通过插件管理界面或安装 API 上传 zip；框架解压到 `data/plugins/subtitle-<version>`，
  安装 manifest 声明的依赖，更新数据库清单。
- 升级时提高 `manifest.version`，框架会用新版本目录替换旧目录。
- 可选依赖（`rarfile`、`pysubs2`）在 manifest `backend.dependencies` 或
  `requirements.txt` 中声明，但必须允许缺失：缺失时对应能力降级而不是插件加载失败。

共享命名工具放在 `src/app/services/transfer/subtitle_naming.py`，由插件与
`TransferEngine` 共同使用；插件目录不保留重复实现。

manifest 关键字段：

```json
{
  "id": "subtitle",
  "version": "1.0.0",
  "backend": {
    "entry": "backend.plugin:SubtitlePlugin",
    "hooks": ["subtitle.download"],
    "tools": []
  },
  "frontend": {
    "routes": [
      {"path": "upload", "component": "UploadPage", "title": "字幕管理", "icon": "lucide:subtitles"},
      {"path": "rename", "component": "RenamePage", "title": "识别重命名", "icon": "lucide:file-pen-line"}
    ]
  }
}
```

## 配置项（manifest frontend.settings.fields）

| key | type | 说明 |
|---|---|---|
| `auto_on_transfer` | switch | 转移后自动下载（默认开） |
| `languages` | multi_select | 优先语言（zh-Hans/zh-Hant/en/ja/ko），决定后缀与排序 |
| `sources` | multi_select | 启用源（assrt/thunder） |
| `assrt_token` | password | Assrt Token（脱敏） |
| `min_score` | input | 最低匹配分（默认 60） |
| `suffix_style` | select | 后缀风格：`nexus`(.chi.zh-cn) / `bcp47`(.zh-Hans) / `iso639`(.zh) |
| `overwrite_policy` | select | 已存在：skip / suffix / overwrite（默认 skip） |
| `sync_policy` | select | 时间轴：off / manual / auto_reference / auto_audio（默认 off） |
| `sync_max_offset_ms` | input | 自动检测允许的最大偏移（默认 60000） |
| `sync_min_confidence` | input | 自动同步最低置信度（默认 0.75） |
| `skip_if_chinese_subtitle` | switch | 已有中文字幕时跳过（默认开） |
| `hard_sub_detection` | select | off / filename（默认）/ ocr |
| `library_roots` | textarea | 允许写入的库根目录白名单（每行一个，按后端解析） |
| `library_delay_seconds` | number | 全量扫描每条之间的延迟（默认 1 秒，按源配额调整） |
| `auto_scan_enabled` | switch | 是否启用定时全量扫描（默认关） |
| `auto_scan_cron` | cron | 定时表达式（默认 `0 4 * * *`） |
| `max_workers` | input | 自动下载并发数（默认 2） |
| `request_timeout` | input | 源请求超时秒数（默认 20） |

`library_roots` 为空时：
- 自动下载：仅允许事件给出的视频同目录，且必须先通过 `StorageBackend` 校验路径；
- 手动上传：目标视频必须位于已配置的媒体库根目录内，否则拒绝并要求先配置白名单。

## 后端 API（register_api）

| 方法 | path | 说明 |
|---|---|---|
| POST | `search` | 搜索候选（不入库），在线程池执行 |
| POST | `download` | 下载最佳候选并落盘，在线程池执行 |
| POST | `upload` | 上传字幕文本/Base64 + 目标/规则，落盘（≤5MB） |
| POST | `locate` | 按 TMDB 定位媒体库视频文件（返回可选项） |
| POST | `rename` | 对已有字幕按视频名/模板重命名 |
| POST | `list_targets` | 浏览白名单内目标目录/视频 |
| GET | `history` | 处理历史/结果（分页，默认 50 条） |
| GET | `test_source` | 源连通性测试（Assrt Token） |

handler 返回 `{"success": bool, "message": str, "data": ...}`。
POST 路由当前由框架统一要求 `plugin:manage`（`api/routers/plugin_framework.py:267`），
因此 v1 的上传/重命名是**插件管理员专属**；若要让媒体库管理员使用，需要框架支持
`library:manage` 或插件自定义权限，不在本 ADR 范围。

### API 线程模型

当前 `_dispatch_plugin_api` 在 async POST 路由中直接调用同步 handler
（`api/routers/plugin_framework.py:232,263`），网络搜索/压缩包处理会阻塞事件循环。
实施本插件前需要以下二选一：

1. 框架层把同步 handler 放到 `run_in_threadpool` 执行（推荐）；
2. 插件 handler 只做参数校验并提交后台任务，接口立即返回 `job_id`。

v1 选择方案 1；`search`/`download`/`upload` 均在线程池中执行，并在 handler 内限制
总耗时（`request_timeout`）。自动下载不走 API，直接使用插件线程池。
框架分发时若 handler 返回 awaitable，需要 `await`；否则插件会被误判为完成。

插件路由在读取 JSON 前需要限制请求体大小（默认 8MB），否则超大 Base64 会先占内存；
`upload` 的 5MB 指的是**解码后的字幕内容**，不是请求体大小。

## 后端详细设计

### 1. 数据模型（backend/models.py）

```python
@dataclass
class SearchQuery:
    tmdb_id: str | None = None
    title: str = ""
    year: str | None = None
    media_type: str = "movie"        # movie/tv/anime
    season: int | None = None
    episode: int | None = None
    languages: list[str] = field(default_factory=lambda: ["zh-Hans"])
    video_path: str | None = None    # 供 Thunder CID 用
    backend_id: str | None = None    # 视频所在存储后端

@dataclass
class Candidate:
    source: str                      # assrt / thunder / ...
    title: str
    language: str                    # 归一化 BCP-47：zh-Hans/zh-Hant/en/ja/ko/mul/und
    format: str                      # srt/ass/ssa
    url: str                         # 下载地址
    score: int = 0                   # 0-100
    downloads: int = 0
    payload: dict = field(default_factory=dict)  # 源相关引用（如 assrt sub id）

@dataclass
class PlaceResult:
    success: bool
    action: str                      # placed/skipped/overwritten/renamed/failed
    backend_id: str = "local"
    language: str = ""
    target_path: str | None = None
    reason: str = ""
    sync_method: str = "none"        # none/manual/reference/audio
    offset_ms: int = 0
    rate: float = 1.0
    sync_confidence: float = 0.0

@dataclass
class SyncAdjustment:
    offset_ms: int = 0
    rate: float = 1.0                # 1.0 表示不变；25/23.976 等帧率修正
    method: str = "manual"           # manual/reference/audio
    confidence: float = 0.0

@dataclass
class RenameRule:
    mode: str = "manual"             # manual / recognize
    backend_id: str = "local"
    target_dir: str | None = None
    target_video: str | None = None
    tmdb_id: str | None = None
    media_type: str = "movie"
    season: int | None = None
    episode: int | None = None
    template: str | None = None
    language: str = "zh-Hans"        # BCP-47 主语言
    flags: list[str] = field(default_factory=list)  # forced/sdh/cc/commentary
    suffix_style: str = "nexus"
    overwrite_policy: str = "skip"
    recursive: bool = True
    sync: SyncAdjustment = field(default_factory=SyncAdjustment)

@dataclass
class SubtitleInput:
    filename: str
    content: bytes
    language: str | None = None      # 用户指定优先
    detected_language: str | None = None  # 插件识别结果
    flags: list[str] = field(default_factory=list)
    confidence: int = 0
    season: int | None = None
    episode: int | None = None

@dataclass
class MatchCandidate:
    video_path: str
    backend_id: str = "local"
    confidence: int = 0              # 0-100
    reason: str = ""
    title: str = ""
    year: str | None = None
    season: int | None = None
    episode: int | None = None
    flags: list[str] = field(default_factory=list)

@dataclass
class UploadMapping:
    subtitle_filename: str
    video_path: str
    backend_id: str = "local"
    language: str = "zh-Hans"
    flags: list[str] = field(default_factory=list)
    season: int | None = None
    episode: int | None = None
    suffix_style: str = "nexus"
    template: str | None = None
    sync: SyncAdjustment = field(default_factory=SyncAdjustment)
```

### 2. 插件入口（backend/plugin.py）

```python
class SubtitlePlugin:
    def __init__(self, ctx, mediaserver=None, media_service=None, filetransfer=None,
                 event_bus=None, app_context=None):
        ...
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="subtitle")
    def on_enable(self): self._register_apis()
    def on_disable(self):
        self._ctx.unregister_all_apis()
        self._executor.shutdown(wait=False, cancel_futures=True)
    def on_hook(self, event: str, data: dict):
        if event == "subtitle.download":
            self._executor.submit(self._auto_download, data)

    def agent_tool(self, name: str, arguments: dict):
        if name == "subtitle_search":
            return self._agent_search(arguments)
        if name == "subtitle_download":
            return self._agent_download(arguments)
        return {"success": False, "error": f"未知工具: {name}"}
```

- `subtitle.download`：普通文件触发；`bluray=true` 或 `file` 为空时跳过。
- `media.transfer_finished`：仅当 `target_path` 是目录时按蓝光处理；
  在 `BDMV/STREAM` 中选最大 `.m2ts` 作为主视频。
- `_auto_download`：指纹去重（store）→ 各源 `search` → `matcher` **按启用语言逐语言选优**
  （同一语言取最高分，不因高分中文跳过英文）→ `download` → `placer.place`
  （StorageBackend）→ 记录历史/可选 `ctx.notify`。
- 线程池在 `on_disable` 中关闭；插件重载不会遗留后台线程。

### 2.1 Agent 工具（manifest `backend.tools`）

框架支持插件声明式 Agent 工具：manifest `backend.tools` 声明 schema，
`ToolExecutor` 合并后通过 `plugin_framework_service.call_agent_tool` →
`sandbox.call(plugin, "agent_tool", name, arguments)` 分发（`tool_executor.py:4-5`、
`plugin_framework_service.py:267-303`）。本插件声明：

```json
"tools": [
  {
    "name": "subtitle_search",
    "description": "搜索字幕候选（不入库）",
    "parameters": { "type": "object", "properties": { "title": {"type":"string"}, "year": {"type":"string"}, "tmdb_id": {"type":"string"} }, "required": ["title"] },
    "level": "read",
    "permission": "library:manage"
  },
  {
    "name": "subtitle_download",
    "description": "下载最佳字幕并落盘到视频同目录",
    "parameters": { "type": "object", "properties": { "tmdb_id": {"type":"string"}, "type": {"type":"string"} }, "required": ["tmdb_id"] },
    "level": "dangerous",
    "permission": "library:manage"
  }
]
```

`agent_tool` 返回 `{"success": bool, "data": ..., "error": str}`，由 ToolExecutor 统一转换。
工具权限使用 `library:manage`；`subtitle_download` 会写文件，必须声明 `level: "dangerous"` 才能触发 ToolExecutor 的用户确认（`write` 级别不会弹确认）。

### 3. 存储后端解析

`placer`、`media_locator`、`thunder.py` 不直接使用 `os.path`/`open` 操作媒体库。

- 事件/规则中的路径先按媒体库根目录做最长前缀匹配，解析出 `backend_id` 和
  `StorageBackend`（复用 `media_config_service` 的路径/后端配置）。
- 本地后端：`StorageBackend.read_stream`/`write_stream`/`move`；需要原子写时用
  `tempfile + os.replace`，且目标必须通过 `realpath` 校验。
- 远程后端：使用后端自己的 `stat/list_dir/read_stream/write_stream/move`；
  禁止把远程路径传给 `open()` 或 `os.replace()`。
- 路径白名单按“后端 + 规范化路径”判断；`..` 必须在规范化后消失。
- 媒体服务器返回的路径如果与后端路径不一致，先做根目录映射；映射失败则返回空，
  由用户手选，不能盲目写入。

### 4. 源适配（sources/base.py + assrt.py）

```python
class SubtitleSource(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def search(self, q: SearchQuery) -> list[Candidate]: ...
    def download(self, c: Candidate) -> bytes: ...
```

**AssrtSource**（`https://api.assrt.net/v1`，备用域 `api.makedie.me`）：

- Token：在 `assrt.net` 注册后进入用户面板 `usercp.php` 查看/重置；32 位随机串；
  官方默认配额 20 次/分钟（实际以账号面板为准，可能是 10；同 Token 与同 IP 共享配额）。
- 搜索：`GET /sub/search?q=<title>&cnt=<N>`（`cnt` 最大 15），Token 按 API 支持的
  鉴权方式传递（优先请求头），日志必须脱敏；解析 `sub.subs[]` 的 `native_name`/
  `videoname`/`subtype`/`lang.desc`/`lang.langlist`/`down_count` 为 `Candidate`，
  `payload` 存 sub id。
- 详情：`GET /sub/detail?id=<sub_id>` 取 `sub.subs[0].filelist[]`，文件名在 `f`、
  下载地址在 `url`；若 `filelist` 为空（单文件字幕），回退详情里的 `filename`/`url`。
  下载地址有有效期，不能持久化。
- 下载：GET url → bytes；按魔数/扩展名判断 ZIP/RAR：
  ZIP 用标准库 `zipfile` 解压；RAR 用 `rarfile`（缺 `unar`/`unrar` 时该源不可用并在
  `is_available()` 返回 False / 页面提示）。
  压缩包可能包含多个语言/版本的字幕，**不能取首个**；必须按目标语言、格式优先级
  和文件名相似度选择最匹配的一个。
- 限流/重试：Assrt 请求失败按指数退避重试 2 次；全部失败记为源不可用，不阻塞其他源。
- 安全：解压拒绝绝对路径、`..`、符号链接，限制解压大小、条目数与压缩比。

**ThunderSource**（无 Token）：
- CID：文件 ≥60KB 时读取首 20KB、1/3 处 20KB、末 20KB，做 SHA1 并转大写十六进制；
  <60KB 时对整文件做 SHA1。读取视频必须通过 `StorageBackend`，远程后端需支持 seek；
  不支持 seek 时降级为名称搜索。
- 搜索：`GET https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name=<视频文件名>`；
  解析 `data[]` 的 `name/url/ext/cid/languages/score`，过滤 srt/ass/ssa/vtt，
  按 CID 命中优先、简体优先、评分排序，取前 20。
- 下载：GET `url` 返回字幕字节；响应内容仍需经过内容校验/UTF-8 转换。
- 接口为非官方公开接口，可能变更；失败时只影响 Thunder，不阻塞 Assrt。

**ZimukuSource**（字幕库，网页 + 验证码）：
- 搜索：`GET https://zimuku.org/search?q=<title>&chost=zimuku.org`；页面返回云锁验证码
  （BMP base64 + `security_verify_img`）时：
  1. 提取 `data:image/bmp;base64,...`；
  2. 调用全局 `OcrRecognizer.get_captcha_text(image_b64=...)`（nexus-verify）；
  3. 设置 `srcurl=<原 URL 的 JS charCode hex>`；
  4. GET `...&security_verify_img=<验证码文本 hex>`，最多重试 3 次。
- 解析：`div.item` → `p.tt a[href]`；字幕行 `div.sublist tbody tr`；
  详情 `td.first a[href]`；语言从行内 `img` 的 alt/title/src 识别；格式从行文本/标题识别。
- 下载：详情页 `a#down1[href]` → 中转页 `a[rel~=nofollow][href]` → 最终文件；
  ZIP/RAR 安全解压并选择目标语言字幕。
- 站点无公开 API，HTML/验证码流程可能变化；OCR 不可用或识别失败时只跳过 Zimuku。

### 5. 匹配打分（backend/matcher.py）

- `normalize(title)`：去标签/标点/大小写/年份括号，统一中英文与分隔符。
- 打分（0-100）：名称相似度 + 年份匹配（`|diff|<=1` 满分，否则按差值递减）+
  季集精确匹配（剧集时命中加分、错季减分）+ 语言命中 + 格式偏好
  （`ass>srt>ssa`）+ 下载量热度。
- 名称相似度优先使用标准库 `difflib.SequenceMatcher`，避免新增 `rapidfuzz` 依赖；
  如果后续确认需要更高精度，再单独引入并记录依赖。
- 流程：`score_all(candidates)` → 过滤 `< min_score` → 同语言去重（取最高）→ 排序。

### 6. 落盘（backend/placer.py）

- `build_subtitle_path(video_path, language, flags, ext, suffix_style)`：
  `base = splitext(video_path)[0]`；语言先规范化为 BCP-47，再按风格输出：
  - `nexus`（兼容存量库）：zh-Hans→`.chi.zh-cn`、zh-Hant→`.zh-tw`、
    en→`.eng`、ja→`.jpn`、ko→`.kor`、mul→`.mul`、其他→`.und`；
  - `bcp47`：`.zh-Hans`、`.zh-Hant`、`.en`、`.ja`、`.ko`、`.mul`、`.und`；
  - `iso639`：`.zh`、`.en`、`.ja`、`.ko`、`.mul`、`.und`（zh-Hans/zh-Hant 都输出 `.zh`，
    无法区分简繁，UI 需提示）。
- **字幕标记**：`forced` / `sdh` / `cc` / `commentary` / `default` 追加在语言之后，
  按固定顺序去重；例如：
  - `Movie (2020).zh-Hans.srt`
  - `Movie (2020).zh-Hant.srt`
  - `Movie (2020).zh-Hans.forced.srt`
  - `Movie (2020).en.sdh.srt`
  - `Movie (2020).mul.bilingual.srt`（双语/多语言文件）
- **白名单**：规范化后的目标路径必须落在 `library_roots` 或事件视频同目录内，
  并且属于同一 `backend_id`；否则拒绝。
- **冲突策略**：`skip`→返回 skipped；`suffix`→在扩展名前追加 `.1/.2`；
  `overwrite`→覆盖。同名不同语言/标记不算冲突。
- **多字幕**：同一视频允许多个目标文件，只要语言/标记组合不同；相同组合按冲突策略处理。
- **写入前**：编码探测（GB18030/GBK/UTF-8）→ 统一转 UTF-8；内容校验（含时间轴/首条）
  只适用于文本字幕（`.srt/.ass/.ssa/.vtt`）；二进制格式 `.sup/.sub/.idx` 不做内容校验，
  只做扩展名/大小/路径校验。`.sub` 必须与同名 `.idx` 成对上传，缺失则拒绝。
- **原子写**：先写同目录临时文件，再 `StorageBackend.move` 覆盖；失败不留下半文件。
- **并发**：同一目标路径使用 `library:subtitle:{backend_id}:{path}` 锁，避免自动下载
  与手动上传同时写同一字幕。

### 7. 定位（backend/media_locator.py）

`locate(tmdb_id, media_type, season, episode)`：

1. 优先查询 `MEDIASYNC_ITEMS`（`PATH` 字段，`models/media_sync.py:26`）或
   `MediaServer` 新增的按 TMDB 查路径方法；返回 `{video_path, backend_id, ...}`。
   现有客户端 `get_movies`/`get_tv_episodes` 不返回路径，不能直接使用。
2. 剧集按 `season`/`episode` 过滤（电影单条）。
3. 回退：`media_service` 查 TMDB 元数据 → `path_resolver.get_dest_path_by_info(dest, meta)`
   + 名称格式 → 通过 `StorageBackend` 扫描目录找视频。
4. 媒体服务器路径映射不到后端时返回空，前端提示手选；不猜测路径。

### 7.1 手动上传的媒体匹配策略

手动上传分两阶段：**匹配（match）** → **确认落盘（upload）**。落盘阶段只接受用户确认过的
`UploadMapping`，不再在写入时重新猜媒体。

匹配优先级（从高到低）：

1. **用户显式选择视频**：`target_video` + `backend_id`，置信度 100。只校验路径存在、
   位于白名单且是视频文件。
2. **TMDB 精确定位**：`tmdb_id + type + season + episode`，通过 `MEDIASYNC_ITEMS.PATH`
   或媒体服务器路径查询，置信度 95。多条结果必须让用户选，不能自动取第一条。
3. **字幕文件名解析**：先去掉字幕扩展名和语言后缀（`.zh/.chs/.cht/.eng` 等），
   再用 `meta_info()` 解析 title/year/season/episode，在当前目录/根目录内匹配视频，置信度 80。要求：
   - 片名归一化后相同或高度相似；
   - 年份差 ≤ 1；
   - 剧集 season/episode 完全一致；
   - 匹配结果唯一。
4. **目录唯一视频兜底**：目标目录恰好只有 1 个视频时，置信度 70，仍需用户确认。
5. **模糊匹配**：只允许作为候选提示，置信度 < 70；默认不写入，必须用户手选。

匹配规则：

- **电影**：title + year；同片多个版本（1080p/4K）不自动选，列出候选让用户选。
  用户可显式选择「应用到该目录内所有同片版本」，插件为每个视频各生成一份字幕。
- **剧集**：season + episode 是硬条件；字幕文件名可解析 `S01E02`、`1x02`、`E02`、
  `第02集` 等。多集视频（`S01E01-E02`）按区间匹配。
- **批量字幕**：每个字幕文件独立解析/匹配；同一集出现多个字幕（不同语言）按语言区分；
  同一集出现多个候选视频时逐条冲突，全部要求用户确认。
- **动漫绝对集号**：如果字幕文件名只有绝对集号、没有 season/episode，优先用
  `MEDIASYNC_ITEMS`/TMDB 的季集映射；无法映射时进入手选，不做 `集号=集数` 猜测。
- **文件名不可解析**：进入 `needs_confirmation`，不写入。
- **语言**：从字幕文件名/内容探测；语言不参与目标视频选择，只决定后缀。
- **后端**：所有候选必须属于同一个 `backend_id`；跨后端候选不自动匹配。

数据结构：

```text
MatchRequest:
  files: [{filename, size, language?, season?, episode?}]
  mode: target_video | tmdb | filename | directory
  backend_id?, target_dir?, target_video?, tmdb_id?, type?, season?, episode?

MatchResponse:
  [{filename, candidates: [{video_path, backend_id, confidence, reason,
                            title, year, season, episode}],
    selected?: {video_path, backend_id}}]

UploadRequest:
  files: [{filename, content(base64|text), language?}]
  mappings: [UploadMapping]
  suffix_style, overwrite_policy, dry_run
```

`upload` 收到 `mappings` 后逐条重新校验：视频存在、同一后端、在白名单内、字幕扩展名合法；
任一校验失败只影响该条，不写入其他条。

### 7.2 多语言、多字幕与识别重命名

#### 语言与标记

内部统一使用 BCP-47 语言标签，输出时再按 `suffix_style` 转换：

| 输入别名 | 规范化 |
|---|---|
| `zh`, `zh-CN`, `zh-SG`, `zh-Hans`, `chs`, `sc`, `简体`, `简中` | `zh-Hans` |
| `zh-TW`, `zh-HK`, `zh-Hant`, `cht`, `tc`, `繁体`, `繁中` | `zh-Hant` |
| `en`, `eng`, `english`, `英语` | `en` |
| `ja`, `jpn`, `japanese`, `日语` | `ja` |
| `ko`, `kor`, `korean`, `韩语` | `ko` |
| `zh-Hans&en`, `chs&eng`, `中英`, `双语`, `bilingual` | `mul` + `bilingual` 标记 |
| `und`, `unknown`, 空 | `und` |

字幕标记：`forced`、`sdh`、`cc`、`commentary`、`default`、`bilingual`。
标记从文件名提取，用户可在 UI 中勾选/取消；标记顺序固定，避免同名文件因顺序不同重复。

#### 多字幕

- 同一视频可同时存在多条字幕：`zh-Hans`、`zh-Hant`、`en`、`zh-Hans.forced`、
  `en.sdh` 等；目标文件名 = 视频基名 + 语言 + 标记 + 扩展名。
- 已存在判断按“语言 + 标记”组合，不按“视频是否有任意字幕”：
  已有 `zh-Hans` 不应阻止下载 `en` 或 `zh-Hans.forced`。
- 同一组合冲突时按 `overwrite_policy`；`suffix` 追加 `.1/.2`，不能覆盖其他语言。
- 双语字幕规范化为 `mul` + `bilingual`，例如 `Movie.mul.bilingual.srt`；
  不使用两个语言标签拼接（媒体服务器无法可靠识别）。
- 多版本视频（1080p/4K）默认不自动选；用户可显式选择“应用到全部版本”，
  插件为每个视频各写一份同语言/标记字幕。

#### 识别重命名（已有字幕）

支持两种重命名方式：

1. **手动重命名**：用户选择字幕文件 + 目标视频 + 语言/标记，预览后写入。
2. **识别重命名**：扫描指定目录/媒体库根，逐个解析字幕文件名并尝试识别语言/标记，
   再按 §7.1 的匹配规则找视频，返回“旧名 → 新名 + 识别语言 + 置信度”预览；
   用户确认后批量写入。

识别顺序：

1. 文件名语言/标记别名（优先级最高）；
2. 文件名中的 `chs/cht/简/繁/eng/双语` 等显式标记；
3. 内容启发式（CJK 字符占比、简繁字符集、英文比例）；只作为辅助；
4. 无法确定 → `und`，标记 `needs_confirmation`，默认不写入，等待用户手选。

安全与一致性：

- 重命名只改变字幕文件名，不移动视频；目标必须同目录、同后端、在 `library_roots` 内。
- 只接受字幕扩展名（`.srt/.ass/.ssa/.vtt/.sub/.idx/.sup` 等），拒绝把视频/NFO 当字幕。
- `rename` 与 `upload` 共用 `UploadMapping`/`PlaceResult`，都必须支持 `dry_run`。
- 扫描结果按“字幕文件 → 候选视频”分组；低置信度/多候选/同名冲突逐条确认，
  不允许批量静默选择。

### 7.3 时间轴偏移与自动同步

支持三类同步方式，默认 `sync_policy=off`，不允许静默自动纠正：

1. **手动偏移**：用户输入 `offset_ms`（可为负）和 `rate`（默认 1.0），
   预览首条/末条时间后应用。适用于已知固定偏移或帧率转换。
2. **参考字幕对齐**：同一视频已有另一条字幕（通常是英文或其他语言）作为时间参考。
   只用**时间轴**对齐，不依赖文本翻译：取两条字幕的 cue 区间做互相关/最近邻匹配，
   估计 `offset_ms` 和可选 `rate`，输出置信度；低置信度不采用。
3. **音频语音对齐**：通过 ffmpeg 提取单声道音频并做语音/静音检测，将字幕 cue 起始
   与语音区间对齐，估计固定偏移或线性漂移。该方式较慢，只在本地临时文件或可流式读取
   的后端上执行，必须设置超时和临时文件清理。

规则：

- 自动纠偏必须有可靠参考（另一条字幕或音频）；没有参考时只允许手动偏移。
- 参考字幕选择：同一视频已存在的另一条字幕；优先用户指定，否则选择 cue 数最多且
  非目标语言的一条；候选不唯一/无参考时不自动。
- 不允许把字幕自身当作参考；参考字幕必须与目标视频对应且语言/版本不同。
- 自动纠偏失败或低于阈值：保留原时间轴并记录 `sync_skipped`，不影响字幕落盘。
- 偏移超过 `sync_max_offset_ms` 或置信度低于 `sync_min_confidence` → 不采用，保留原字幕。
- 时间变换：`new_time = old_time * rate + offset_ms`；结果必须 `>= 0` 且保持单调，
  异常时拒绝整条字幕。
- 只支持**恒定偏移/线性速率**，不做逐行/逐句自动重排；逐行错位需要人工处理。
- 自动下载默认不同步；只有 `sync_policy=auto_reference`/`auto_audio` 且达到阈值时，
  才在落盘前应用，并把 `sync_method`/`offset_ms`/`rate`/`sync_confidence` 写入历史。
- 手动上传/识别重命名始终展示同步预览，用户可覆盖自动结果。

格式处理：

- SRT 使用现有 `srt` 依赖解析/重写；ASS/SSA/VTT 使用独立时间轴解析器
  （可引入 `pysubs2`，或实现只改 `Dialogue`/cue 时间的轻量解析）。
- 二进制格式（`.sup/.sub/.idx`）不支持时间轴纠偏，只支持重命名/落盘。
- 保留样式、注释和编码转换结果；ASS 的 `Dialogue: Start,End` 与 VTT 的 cue 时间
  必须成对修改，不能只改开始时间。
- 负时间钳制为 0 并记录警告；不要删除字幕行。

### 7.4 蓝光原盘

蓝光目录的 `subtitle.download.file` 为空，插件从 `media.transfer_finished` 的
`target_path` 目录进入：

1. 在 `<disc>/BDMV/STREAM` 中选择最大的 `.m2ts`/`.mts` 作为主视频；
2. `ffprobe` 读取主视频字幕流，检测中文软字幕；
3. 外挂字幕放在主 `.m2ts` 同目录同基名。注意：Emby 官方文档只说明普通视频的
   外挂字幕命名，未确认 BDMV 目录外挂字幕；社区反馈也不保证识别。因此这里只是
   best-effort，若要 Emby 稳定识别，优先 remux 为 MKV；
4. 硬字幕仍使用目录/主视频文件名特征或可选 OCR；
5. 找不到主视频时记录 `bluray_main_not_found`，不阻塞其他任务。

### 7.5 已有中文字幕检测

下载/自动下载前执行，命中则跳过并记录 `chinese_subtitle_exists:<kind>`：

1. **外挂字幕**：扫描视频同目录同基名字幕，解析文件名语言；语言为 `zh-Hans`/
   `zh-Hant`/`mul` 或文本内容含 CJK 时命中。
2. **容器内软字幕**：本地视频直接调用 `ffprobe -select_streams s`；远程后端先通过
   `StorageBackend.read_stream` 读取前 16MB 到临时文件再 ffprobe（MKV/M2TS 的轨道头
   通常在文件前部）。命中 zh/chi/zho/zh-Hans/zh-Hant/中文/简/繁/双语。
3. **硬字幕文件名**：文件名/目录含 `中字/中英/简繁/简体/繁体/中文/双语/内嵌/
   硬字幕/CHS/CHT/ZH` 等特征时命中。
4. **硬字幕 OCR（可选）**：`hard_sub_detection=ocr` 时用 ffmpeg 抽 4 帧、
   裁底部 30%，调用 nexus-verify `TEXT_OCR`，出现 CJK 字符即命中。OCR 不可用
   或抽帧失败时回退文件名检测。

约束：

- 远程软字幕检测复制前 16MB 头部；MP4 等 `moov` 在文件尾部的格式可能无法从头部
  识别，此时回退外挂字幕/文件名检测。
- 硬字幕检测是启发式，存在误判（片名含“中字”但实际无硬字幕）和漏判
  （硬字幕不在底部/抽帧未覆盖）；默认使用文件名，OCR 只作为可选增强。
- `download` API 支持 `force=true` 跳过检测，供用户明确要求时使用。

### 7.6 媒体库全量补字幕

`library/scan` 启动后台 job：

1. 枚举 `BackendResolver.roots()`（可按 `roots`/`media_types` 过滤），用
   `media_match.list_videos` 递归列出视频；按 `(backend_id, path)` 去重。
2. 每个视频执行 §7.5 中文字幕检测；命中则跳过。
3. 缺失时用视频标题/年份/季集构造 `SearchQuery`，按配置语言搜索并落盘；
   `dry_run` 只返回 `would_download`/`exists`，不写文件。
4. `library_delay_seconds` 控制条目间隔，适配 Assrt 等低配额源；单条失败不阻断后续。
5. job 状态持久化到插件 `jobs.json`，支持 `library/job` 查询和 `library/cancel`；
   结果最多保留 200 条，任务最多保留 50 个。

全量任务与事件监听共用 `SubtitleService.download` 和同一落盘/检测逻辑；
事件监听只处理 `subtitle.download`，全量任务是独立入口。

定时任务由 `ctx.schedule_cron("library_scan", ...)` 注册，`on_disable` 中
`ctx.remove_schedule("library_scan")` 移除；插件启用时若配置开启则自动注册，
配置保存后通过 `plugin.config_changed` 重新注册。
定时触发同样受“单飞”保护，已有 running job 时直接跳过并记录日志。

### 8. register_api handlers（请求/响应）

| path | 请求 | 响应 data |
|---|---|---|
| `search` | `{title,year?,tmdb_id?,type?,season?,episode?,languages?}` | `[Candidate 摘要]` |
| `match` | `MatchRequest` | `MatchResponse`（仅匹配，不写文件） |
| `download` | `{tmdb_id,type,season?,episode?,languages?,overwrite?,force?}` | `[PlaceResult]` |
| `upload` | `{files[], mappings[](language/flags/sync), suffix_style, overwrite_policy, dry_run}` | `[{video_path, subtitle_path, action, reason, sync}]` |
| `sync_detect` | `{subtitle_path, video_path, method, reference_path?, max_offset_ms?, min_confidence?}` | `{offset_ms,rate,method,confidence,samples[]}` |
| `locate` | `{tmdb_id,type,season?,episode?}` | `[{video_path,backend_id,title,season,episode}]` |
| `rename` | `{mode: manual|recognize, mappings?, scope?{backend_id,path,recursive}, detect_language?, sync_policy?, suffix_style?, overwrite_policy, dry_run}` | `[{old_path,new_path,language,flags,confidence,action,reason,sync}]` |
| `list_targets` | `{path, backend_id?}` | `[目录/视频项]` |
| `history` | `{page?, page_size?}` | `{items,total}` |
| `test_source` | `{}` | `{ok, message}` |
| `library/scan` | `{roots?, media_types?, dry_run?, limit?}` | `{id,status,total,...}` |
| `library/job` | `{job_id}`（GET query） | `{id,status,total,done,skipped,failed,current,results}` |
| `library/cancel` | `{job_id}` | job 状态 |


统一返回 `{"success": bool, "message": str, "data": ...}`；`dry_run=true` 只计算不写。
`upload` 的 Base64 字符串先校验长度再解码；`upload.mappings` 必须包含语言、标记与同步参数；
`sync_detect` 只计算偏移/速率，不写字幕；`rename` 的 manual 模式逐条校验 mapping，
recognize 模式只接受白名单内的字幕目录/根，并且只处理字幕扩展名；
`list_targets` 不能越出白名单根目录。

### 9. store.py（数据目录 JSON）

- `history.json`：最近 N 条 `{time, title, tmdb_id, source, lang, flags, action, target, result, sync_method, offset_ms, rate, sync_confidence}`；
- `fingerprints.json`：自动下载去重指纹（`tmdb+season+episode+lang+flags+backend_id`），
  设置上限（默认 5000）并按时间淘汰；
- `cache.json`：搜索缓存（TTL，避免重复请求）。

所有写入使用临时文件 + `os.replace` 原子替换，并用进程内 `threading.Lock`
（或文件锁）串行化；插件重载后重新加载。多实例部署共享数据目录时，进程内锁不够，
指纹/历史写入改用分布式锁 `library:subtitle:store`。

### 10. DI 依赖（sandbox 注入键）

注入 `mediaserver`、`media_service`、`filetransfer`、`event_bus`、`app_context`；
仅构造参数名匹配者注入（`sandbox.py:200-215`）。线程池由插件自建，不依赖 DI。

### 11. 实施影响面

- 独立仓库 `~/python/nexus-media/nexus-media-plugins/plugins/subtitle`：插件源码、测试与
  `manifest.json`；打包由仓库根目录 `tools/build_catalog.py` 生成；不修改后端 builtin 插件目录。
- `api/routers/plugin_framework.py`：把同步插件 API handler 放入线程池执行。
- `src/app/plugin_framework/registry.py`：安装/启用后同步 manifest/state 缓存，支持安装后立即启用。
- `src/app/services/transfer/subtitle_naming.py`：抽出共享字幕后缀/命名逻辑，
  `transfer_engine.py` 与插件共同使用。
- `src/app/mediaserver/`：新增或扩展按 TMDB 返回视频路径的查询能力（若不复用
  `MEDIASYNC_ITEMS.PATH`）。
- 插件 manifest 声明 `backend.tools`，由现有 ToolExecutor 合并；无需改 Agent 工具框架。
- 测试：插件仓库内新增 matcher/placer/source/locator/API/事件/Agent 工具/打包安装测试；
  后端新增共享命名与插件 API 线程模型测试。

### 12. 测试

- `matcher`：打分/去重/排序边界；
- `placer`：命名/后缀/覆盖/白名单/目录穿越拒绝/编码转换/原子写；
- `placer` 多语言：`zh-Hans`/`zh-Hant`/`en`/`ja`/`ko`/`mul`、forced/sdh/cc、
  简繁别名、双语（`mul`）、三种 suffix_style；
- `placer` 远程后端：使用 fake StorageBackend 验证 read/write/move 调用，禁止本地 `open`；
- `assrt`：固定样本响应解析、压缩包安全（符号链接/绝对路径/bomb）、Token 脱敏；
- `match`：显式视频、TMDB 精确、文件名解析、目录唯一、模糊拒绝、多候选冲突、
  多版本/多集/动漫绝对集号；
- `rename`：manual + recognize、语言/标记识别、低置信度不写入、同名多语言不冲突、
  同语言不同标记共存；
- `sync`：SRT 正/负偏移、frame-rate `rate`、负时间钳制、单调校验、ASS/VTT 时间成对修改、
  参考字幕置信度、音频 VAD 假数据、超阈值拒绝、无参考不自动；
- 事件：普通文件只触发一次下载；蓝光目录通过 `media.transfer_finished` 处理并找到主 m2ts；
- `locate`：MEDIASYNC_ITEMS 命中、路径映射失败回退、手选兜底；
- `agent_tool`：manifest tools schema、`library:manage` 权限、写工具确认级别、
  返回 `{success,data,error}` 契约；
- 打包/安装：zip 根目录含 manifest、版本升级替换、可选依赖缺失时插件仍可加载；
- 闭环：`match` → `upload` → `rename`（含 dry_run）；
- 并发：自动下载与手动上传同时写同一路径时只允许一个成功。
- 全量任务：dry-run 只检测不下载、已有中文跳过、缺失下载、取消后停止、进度/结果持久化。
- 定时任务：启用时注册 cron、禁用时移除、重叠触发被拒绝。

## 详细页面设计

插件前端为独立 ESM（`frontend/index.mjs`，默认导出 `function(host)`，返回组件映射；
`host` 提供 `Vue`、`IconifyIcon`、`api` 客户端与 `NaiveUI` 命名空间 — `loader.ts:44,56-86`）。

页面使用 host 注入的 Naive UI 组件（`NCard`/`NDataTable`/`NButton`/`NSelect`/`NProgress` 等），
视觉遵循项目规范：`hsl(var(--card|--border|--primary|--accent|--muted-foreground|...))`、
`IconifyIcon`（`lucide:` 前缀）、`grid-cols-1 md:grid-cols-2` 响应式。

### 页面 A：设置（SettingsPage，manifest settings 自动渲染）

- 由框架按 `settings.fields` 渲染，无需手写；
- 顶部可选一卡片展示「源连通性」（调用 `test_source`，红/绿点 + 失败原因）。

### 页面 B：上传 / 重命名（UploadPage，路由 `/plugin/subtitle/upload`）

布局为左右两栏（移动端上下堆叠），左侧「上传与目标」，右侧「匹配与结果」。

**左侧：上传与目标**

1. **上传区**（拖拽或点击选择 `.srt/.ass/.ssa/.vtt/.sub/.idx/.sup`）：
   - 文件卡片：名称、大小、探测语言、格式；可移除；
   - 每个文件可手动修正语言/标记（`zh-Hans`、`zh-Hant`、`en`、`forced`、`sdh`、`bilingual` 等）；
   - 多文件列表（剧集批量/多语言）。
2. **模式切换**（segment 按钮）：
   - 「手动指定」：目标目录选择器（`list_targets` 浏览）+ 目标视频下拉（同目录媒体）；
   - 「按 TMDB ID」：`tmdb_id` + 类型（电影/电视剧/动漫）+（剧集时）季/集 输入；
   - 「按文件名」：解析字幕文件名中的标题/年份/季集，在当前目录或指定根目录内匹配。
3. **命名规则**：
   - 语言（zh-Hans/zh-Hant/en/ja/ko/mul）+ 标记（forced/sdh/cc/commentary/bilingual）；
   - 后缀风格（`nexus` / `bcp47` / `iso639`）；
   - 已存在策略（skip/suffix/overwrite）；
   - 自定义模板（占位符 `{title}{year}{season}{episode}{lang}{flags}{ext}`，含预览）。
4. **时间轴**：
   - 偏移 `offset_ms`（可为负）、速率 `rate`（默认 1.0）；
   - 「自动检测」按钮：选择参考字幕或音频；展示 `offset_ms/rate/confidence` 和首尾时间样本；
   - 自动结果低于阈值或没有参考时不应用，保留原时间轴。
4. 操作按钮：「匹配媒体」（只匹配不写）→ 确认候选后「预览命名」→「上传并落盘」。
   匹配结果中的低置信度/多候选/冲突项必须手动选择，未选择不写入。

**右侧：匹配与结果**

- **匹配结果**：按字幕文件分组，展示候选视频路径、置信度、匹配原因（显式选择/TMDB/文件名/目录唯一）；
  多候选时逐条选择；同一电影多版本可勾选「应用到全部版本」。
- **定位结果**（TMDB 模式）：按季/集分组的视频列表，每个含路径 + 目标字幕名预览 + 状态徽标（将新建/将覆盖/跳过）；
- **执行结果**：逐条「成功 / 失败原因 / 跳过原因」，失败可重试单条；
- **状态设计**：空态（提示先上传/匹配）、加载骨架、错误态（含返回原因，如 TMDB 未定位）、成功态。

**移动端**：`grid-cols-1`；上传区固定为按钮；结果区折叠；操作按钮吸底。

### 页面 C：识别重命名（RenamePage，路由 `/plugin/subtitle/rename`）

用于已有字幕的批量整理，支持“识别重命名”和“手动重命名”。

1. **范围**：选择后端/目录或媒体库根；是否递归；是否启用内容语言识别。
2. **扫描/预览**：表格列：
   - 旧字幕路径、视频路径、新字幕名；
   - 识别语言（下拉可改）、标记（多选）、置信度、动作（将重命名/跳过/冲突）；
   - 时间轴偏移/速率/同步置信度（可手动改，也可对单条执行 `sync_detect`）；
   - 低置信度、多候选、同名冲突、自动同步失败行高亮，必须逐条确认。
3. **手动重命名**：选中字幕行后指定目标视频 + 语言/标记，预览后执行；不移动视频。
4. **执行**：`dry_run` 预览 → 批量/单条应用；失败可重试单条；不覆盖其他语言/标记。

### 页面 D（可选）：历史（HistoryPage）

- 表格/时间线：时间、媒体（标题/年份）、语言、动作（自动下载/上传/重命名）、源、目标路径、结果；
- 过滤：媒体类型、结果、源；分页加载；点击查看详情。

## 交互/状态要点

- 预览与落盘分离（先「预览命名」再「上传并落盘」）；
- 批量时逐条独立成败，整体完成后汇总通知；
- 失败原因可读（TMDB 未定位 / 已存在跳过 / 越白名单 / 内容校验失败）；
- 大文件/网络失败给出重试入口；
- 可达性：所有按钮可键盘聚焦，图标带 `aria-label`。

## 错误处理

| 场景 | 处理 |
|---|---|
| Assrt 无 Token / 401 | 提示配置 Token，跳过搜索 |
| 源超时/网络失败 | 标记失败可重试，不中断批量 |
| 无候选 ≥ min_score | 记日志/可选通知，跳过 |
| 响应为 HTML/空 | 丢弃（防止存错内容） |
| 压缩包含 `..`/绝对路径/符号链接/超限 | 拒绝并记录 |
| 压缩包含多语言/多版本 | 按目标语言/格式/文件名选择，不取首个 |
| 路径越白名单/跨后端 | 拒绝并提示 |
| 二进制 `.sup/.sub/.idx` | 不做内容校验；`.sub` 缺同名 `.idx` 拒绝 |
| 同名已存在 | 按 overwrite_policy 处理 |
| 蓝光原盘 | 从 `media.transfer_finished.target_path` 找主 m2ts；找不到则跳过 |
| 媒体服务器路径无法映射到后端 | 返回空结果，要求手选 |

## 依赖

- 标准库：`zipfile`、`difflib`、`chardet`/`charset-normalizer`（编码探测）。
- 现有依赖：`srt`（SRT 解析/重写）。
- 可选：`pysubs2`（ASS/SSA/VTT 时间轴修改）；未安装时这些格式只做重命名，不自动纠偏。
- 可选：系统 `ffmpeg`/`ffprobe`（音频语音对齐、软/硬字幕检测）；缺失时跳过对应检测。
- 可选：`rarfile`（Python 包）+ 系统 `unar`/`unrar`；`rarfile` 本身只是解压前端，
  不包含 RAR 解码器。缺失时 Assrt/Zimuku 的 RAR 包不可用，ZIP 不受影响。
- Zimuku 依赖全局 `laboratory.ocr_server_host`（nexus-verify）；未配置或不可达时该源报错跳过。
- 不引入 `rapidfuzz`；若后续需要更高匹配精度，再单独评估依赖与体积。

## 里程碑（增量落地）

1. **Slice 1**：骨架 + 配置 + `subtitle.download` hook + Assrt 源 + 共享命名/落盘/去重 + 单测。
2. **Slice 2**：上传/识别重命名页（手动/TMDB/文件名匹配）+ `match`/`upload`/`rename`/`list_targets` API + 手动偏移/速率预览 + 线程池/原子写。
3. **Slice 3**：`locate`（MEDIASYNC_ITEMS/媒体服务器路径）+ 自动重命名 + `sync_detect`（参考字幕/音频）。
4. **Slice 4**：Thunder/Zimuku 源完善 + 全量补字幕 + `test_source` + 历史页。
5. **Slice 5**：Agent 工具（`subtitle_search` / `subtitle_download`）+ 权限/确认级别测试。
6. **Slice 6**：通知、文档、全量测试与发版。

## 风险 / 待决

- **Thunder 接口**为非官方公开接口，可能随时变更；CID 需要远程后端支持 seek，
  不支持时降级名称搜索；Thunder 结果仍需内容校验。
- **全量任务配额**：Assrt 每个视频通常需要搜索 + 详情 + 下载请求，低配额账号
  需要增大 `library_delay_seconds`，否则会出现 `quota` 失败；失败项可重跑。
- **定时任务重叠**：cron 触发时若上一次全量任务仍在运行，本次跳过；进程重启后
  正在运行的 job 不会自动恢复，需要重新触发（state 保留为历史记录）。
- **Zimuku 验证码**依赖 nexus-verify OCR，识别率/可用性会直接影响该源；站点 HTML
  和云锁流程变化也会导致失效。不要高频请求，失败时跳过。
- **已有字幕检测**：远程软字幕依赖前 16MB 头部探测，MP4 `moov` 在尾部时可能漏检；
  硬字幕 OCR 只覆盖抽帧的底部区域，可能误判/漏判。默认使用文件名特征，必要时让用户手动确认。
- **Emby 蓝光外挂字幕**：官方文档未确认 BDMV 目录外挂字幕；2019/2021 社区反馈均不保证
  识别。插件可以写入主 `.m2ts` 同目录，但不能承诺 Emby 会加载；需要稳定效果时建议
  将 BDMV remux 为 MKV。
- **全量扫描耗时**：逐视频检测/搜索/下载是 I/O 密集操作；默认串行并受
  `library_delay_seconds` 限制，大型媒体库建议先用 `dry_run` 预览缺失清单。
- **RAR 解压**依赖系统 `unrar`，缺失时降级为仅 ZIP 并在页面提示。
- **TMDB→文件定位**依赖 `MEDIASYNC_ITEMS.PATH` 或新增媒体服务器路径查询；
  `MEDIASYNC_ITEMS.PATH` 只有 255 字符，长路径可能被截断；定位失败时回退
  `path_resolver`，再失败则手选。
  媒体服务器路径与后端路径不一致时只能手选。
- **插件 API 线程模型**：依赖框架把同步 handler 放入线程池；若暂不改造，在线 handler
  只能做快速校验并提交后台任务。
- **权限**：POST 固定 `plugin:manage`，本 v1 仅插件管理员可上传/重命名。
- **语言识别**：内容启发式只用于辅助简繁/中英判断，不能保证准确；无法确定时标 `und`
  并要求用户确认。文件名显式标签优先。
- **`iso639` 风格**：`zh-Hans`/`zh-Hant` 都会写成 `.zh`，无法区分简繁；UI 必须提示，
  需要区分时使用 `bcp47`。
- **`mul`/`bilingual`**：不同媒体服务器对 `mul` 和自定义标记的识别程度不同；
  不识别时仍能作为普通字幕文件存在，但语言展示可能不理想。
- **自动纠偏风险**：音频 VAD/参考字幕对齐都可能误判；默认 `sync_policy=off`，
  自动结果必须达到置信度阈值并保留预览，不能静默覆盖原时间轴。
- **纠偏范围**：只支持恒定偏移/线性速率；逐行错位、乱序、缺失 cue 不做自动重排。
- **格式支持**：SRT 使用现有 `srt`；ASS/SSA/VTT 依赖可选 `pysubs2`，缺失时只重命名不纠偏。
- **音频纠偏成本**：ffmpeg 提取音频与 VAD 较慢，必须限制文件大小/时长、设置超时并清理临时文件。
- **远端存储**：SMB/WebDAV/S3/OpenList 的 `write_stream`/`move` 语义不同，跨后端复制
  可能退化；需预留失败回滚与临时文件清理。
- 字幕属共享资源，自动覆盖默认 `skip`，谨慎。
