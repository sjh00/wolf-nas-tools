# sjh00 贡献备份与 v4 迁移 spec

> 本文档用于在 rebase 到 `linyuan0213_nexus-media/master`（v4，tip=`fefa7572`，2026-07-05）后对照使用。rebase 前逐一"备份"sjh00 主要贡献的语义；rebase 后逐项检查 v4 是否已实现或更好，未实现且 sjh00 老代码更好的再手动迁移。
>
> 本地备份文档，未 commit；rebase 后该文件可能需要重新落位或删除。

## 概览

- 上游基线：`linyuan0213_nexus-media/master` 与 `linyuan0213_nas-tools/master` 均被强制重置到 `fefa7572`（C.C，2026-07-05），属于 v4 重写（代码迁到 `src/app/`，采用 services/domain/di/schemas 分层架构）。
- `dev` 上 sjh00 authored 的非 merge 提交共 60 个，构成本次备份全集。
- `git merge-base dev linyuan0213_nexus-media/master` = 空（两条历史无共同祖先）→ 这就是"无法 merge 只能 rebase"的根因。
- 沿用决策（来自用户）：
  - 用户认证：确保最终无任何"需认证才能继续使用"的拦路逻辑。**v4 已无 sjh00 当年要绕开的"三方验证码激活门"**，无需沿用 `ffad6103`。
  - 过滤规则指定原始语言（E 组）：是主要贡献，v4 缺失，rebase 后补加。
  - B/C/D：先提炼备份，rebase 后逐项对照 v4 现状再迁移。

### 贡献 vs v4 现状速查

| 组 | 设计点 | 是否已在 v4 实现 | 处置 |
|---|---|---|---|
| B | 序号前缀/重复年份/无年份兜底/onlyen 中文二次纯英匹配 | 未确认（需逐项对照 v4 `src/app/media/`） | rebase 后逐项验证 |
| B | Season 在标题里被误剥离（`The Long Season` / `Cherry Season`） | 未确认 | 强烈保留 |
| B | 集范围正则 `EP?\d{1,3}[ \.]\d{1,3}` | 未放宽 `_episode_re`（v4 仍 `S\d{2}EP?(\d{2,4})`） | 与 D 组同补 |
| B | 历史记录/未识别页：每页条数/失效项/正则搜索/防抖 | v4 前端已为 SPA；后端可能仍需补 isexists 字段 | 前端在新组件里等价重写 |
| C | 手动下载回写电影订阅（finish/over_edition） | v4 已有 finish/over_edition 能力，但手下载链路未连接 | 部分迁移 |
| C | RSS 站点限定小时内订阅 (`withinhour`) | v4 `rss_processor.py` 无该过滤 | 未实现，可补 |
| C | 「只订阅不搜索」哨兵 `["#dontuse"]` | v4 用 `SubscribeState` 状态机等价承担 | 不迁移，按 v4 模式 |
| D | TV 文件名 `OF` token 边界 | v4 `name_parser.init_name` 无 OF 分支 | 未实现，建议补 |
| D | URL 含 `+` 处理（Jinja `urlquote` 双重编码） | v4 前端框架级编码替代 | 需求验证 |
| D | BONUS/花絮整套转移能力 | v4 path_utils/filetransfer/path_resolver grep 全无 extras/bonus | 未实现，整套补 |
| E | 过滤规则指定原始语言 | v4 三处规则引擎 + DB schema + entity 全无 | rebase 后补加 |

---

## 一、用户认证结论

- v4 tip 没有 `.so/.pyd` 编译后二进制 user 模块（sjh00 当年 `ffad6103` 删的那批东西在 v4 里压根不存在）。
- v4 虽有 RBAC（`src/app/services/rbac/`、`src/app/services/auth_service.py`），但那是**用户登录/权限**，不是 sjh00 要绕开的"三方站点验证码才允许使用"门。
- grep v4 tip 没有任何"软件激活码/联网验证授权"逻辑。
- ⇒ "无恶心认证"诉求在 v4 base 上天然满足，`ffad6103` 无需沿用。

---

## 二、B 组 — 标题/名称识别引擎（16 个提交）

### 6beeffc9 对于没有年份的电影电视剧，尝试判断为今年
- **改动文件**：`app/media/media.py`
- **设计目标**：当种子/文件名未识别出年份时，TMDB 搜索容易命不中或拿到错乱结果。本提交在搜索前把 `meta_info.year` 临时填为当前年份，让"无年份"标题也能按带年份的电影/电视剧检索分支走。
- **核心逻辑**：在 `__get_media_info` 与 `get_media_info_on_files` 修正名称分支中，调用 `__search_tmdb(...)` 之前：
  ```
  if not meta_info.year:
      meta_info.year = date.today().year
  ```
  仅作搜索条件补全，不影响最终元数据年份（TMDB 命中后以 TMDB 返回为准）。引入 `from datetime import date`。
- **迁移关注点**：v4 对应逻辑在 `src/app/services/media_info_service.py` 的搜索调度处。若 v4 已有更完善的"无年份→多候选年份搜索"机制（逐年猜测或多搜索），不必迁这台硬塞当年。

### a026cdc1 完善含中文标题的识别
- **改动文件**：`app/media/media.py`、`app/media/meta/_base.py`、`app/media/meta/metaanime.py`、`app/media/meta/metainfo.py`、`app/media/meta/metavideo.py`
- **设计目标**：当标题以中文为主、英文识别把中文混入造成 TMDB 匹配失败时，提供"只识别英文名称"的二次尝试通道，并修正电影年份+标题双重比对的逻辑短路问题。
- **核心逻辑**：
  1. `MetaInfo/MetaAnime/MetaVideo/MetaBase` 全链路新增 `onlyen` 参数；`MetaVideo.__init_name_token` 处理中文 token 时：
     ```
     if StringUtils.is_chinese(token):
         if not self.onlyen:
             # 原有把 token 作为 cn_name 的逻辑
         # else: onlyen=True 时跳过中文 token，不写入 cn_name
     ```
  2. `Media.get_media_info` 增加 `onlyen=False` 参数，结尾兜底：
     ```
     if not file_media_info and StringUtils.is_chinese(meta_info.get_name()):
         return self.get_media_info(..., onlyen=True)
     ```
  3. `__search_tmdb` 内电影分支原先两次 `__compare_tmdb_names` 分别 return，改为先校验年份再 OR 比对 title/original_title：
     ```
     if movie.release_date[0:4] == str(first_media_year):
         if __compare_tmdb_names(name, title) or __compare_tmdb_names(name, original_title):
             return movie
     ```
  4. 把 `get_media_info_on_files` 中那段巨大的"修正名称+缓存+TMDB"内联代码抽取为独立方法 `__get_media_tmdbinfo_on_file_with_notmdbinfo(...)`；同时修 `meta_info.org_string = parent_name` 原先漏赋值，避免 onlyen 重跑时丢失原始串。
- **迁移关注点**：onlyen 这套"中文标题二次纯英匹配"策略需对照 `src/app/media/` 下新 Meta 类与 `media_info_service.py`。若 v4 已用 tmdb multi-search / 别名表做中英文回退可能已覆盖。

### 233b55e6 完善手动识别
- **改动文件**：`web/action.py`、`web/main.py`、`web/static/js/util.js`、`web/templates/rename/unidentification.html`
- **设计目标**：手动识别/未识别记录页补"每页条数可调"与"已不存在路径的可视化与批量选择"，并修 `pagenum/current_page` 字符串未转 int、`PageNum` 误传为 `currentPage` 的 bug。
- **核心逻辑**：
  - `WebAction` 处理未识别列表时给每条记录加 `isexists = os.path.exists(path)`；批量重新识别时跳过已不存在的项。
  - `web/main.py` 各页面统一：`pagenum = int(...) or 30`、`current_page = int(...) or 1`；模板 `PageNum` 改用 `Result.get("pageNum")`。
  - `util.js` 新增 `select_dataop_SelectALL(status, name, dataoption)` 按 `data-<option>` 自定义属性过滤全选。
  - 模板 `unidentification.html`：每页条数下拉 `(30,50,100,200,300,500,1000)`；`isexists=False` 行用 `<del class="text-warning">`+"（路径已不存在）"；checkbox 加 `data-notexists="true"`；新增"选择无效项"按钮 `checknotexists_curpage()`。
- **迁移关注点**：v4 前端已迁 SPA，后端 `isexists` 标记需在新 history/unknown list API 里保留；前端"每页条数 + 选择无效项"应在 v4 对应 Vue/React 组件里实现。

### 3de1b8dc 处理如标题[英文,分隔符,中文]英文的情况
- **改动文件**：`app/media/meta/metavideo.py`
- **设计目标**：修正 `e3f5e727` 引入的"去掉'第一季/共三季'等词"逻辑在标题形如 `英文名 中文名 第一季 英文名` 时的副作用——前面英文不应作为独立 `en_name` 留下，而应并入中文标题。
- **核心逻辑**：处理首中文 token 时先检查 `self.en_name`：
  ```
  if not self.cn_name:
      token = re.sub(r'[全共第][0-9一二三四五六七八九十]+季全?', '', token, re.IGNORECASE)
      if self.en_name:
          self.cn_name = "%s %s" % (self.en_name, token)
          self.en_name = ''
      else:
          self.cn_name = token
  ```
- **示例**：`Movie Name 电影名 S01 ...` 应得 `cn_name="Movie Name 电影名"`，而不是 `en_name="Movie Name"`/`cn_name="电影名"` 导致搜索分裂。

### e3f5e727 去除名称中直接跟"第一季""共三季"等词的情况
- **改动文件**：`app/media/media.py`、`app/media/meta/metavideo.py`
- **设计目标**：(1) MetaVideo 在首个中文 token 上剥掉直接粘连的"第一季/共三季/第二季"等词；(2) 把媒体级"修正名称"逻辑从"仅电影/未知"扩展到电视剧，并新增"标题结尾重复年份"修正。
- **核心逻辑**：
  - metavideo 中文首 token 分支前加：
    ```
    token = re.sub(r'[全共第][0-9一二三四五六七八九十]+季全?', '', token, re.IGNORECASE)
    ```
  - media.py 修正名称判定不再限 MOVIE/UNKNOWN：
    ```
    fmnspaceindex = meta_info.get_name().find(' ')
    if fmnspaceindex > 0 and name[:fmnspaceindex].isdigit():
        modifiedname = name[fmnspaceindex+1:]
    fmnendswithyear = ' %s' % meta_info.year
    if name.endswith(fmnendswithyear):
        modifiedname = name[:-len(fmnendswithyear)]
    ```
- **迁移关注点**：上面正则需在 v4 的中文 token 清洗处保留；"序号前缀/重复年份尾巴"修正逻辑应在 `media_info_service.py` 的 modifiedname 计算处保留。

### 7c756d45 / c5fd18ab fix 标题含罗马数字的情况 + Revert（合并说明）
- **设计目标**：`7c756d45` 试图把"罗马数字 token"从"和阿拉伯数字混处理"中拆出独立走"拼装到已有 cn_name/en_name"分支，避免罗马数字（II/III）被误判为集/年。`c5fd18ab` 30 分钟后 revert，说明引入回归（怀疑把 S02 误并入标题）。
- **核心逻辑（7c756d45）**：
  ```
  if token.isdigit():
      ...
  elif is_roman_digit:
      if _last_token_type == "cnname":
          cn_name = "%s %s" % (cn_name, token)
      elif _last_token_type == "enname":
          en_name = "%s %s" % (en_name, token)
      _continue_flag = False
  ```
  `c5fd18ab` 把 `is_roman_digit` 重新合并回旧分支，恢复原行为。
- **迁移建议**：仅作为"已知未解决问题"标注，迁移时优先对照 v4 metavideo 等价类罗马数字处理是否更稳健；**不要把这台已被回退的旧 hack 迁过去**。

### 7bbdf168 添加识别过程检索名称排除前面为序号的情况
- **改动文件**：`app/media/media.py`
- **设计目标**：标题若以纯数字序号开头（`1 影片名`、`03.Movie.Title`），TMDB 直接用全名搜索会失败。本提交在 `__search_tmdb` 末尾兜底：未命中且开头是空格分隔的纯数字，则去数字段重搜一次。
- **核心逻辑**：
  ```
  if not info:
      fmnspaceindex = file_media_name.find(' ')
      if fmnspaceindex > 0 and file_media_name[:fmnspaceindex].isdigit():
          return self.__search_tmdb(file_media_name=file_media_name[fmnspaceindex+1:], ...)
  ```
- **迁移建议**：已被 `75d31dbf` 取代，迁移时以 `75d31dbf`/`e3f5e727` 的"modifiedname + cache_key"方案为准，**不必单独迁这台**。

### 75d31dbf fix 添加识别过程检索名称排除前面为序号的情况
- **改动文件**：`app/media/media.py`、`app/media/meta/_base.py`
- **设计目标**：修正 `7bbdf168` 两处问题：(1) 把"开头序号剥离"从 `__search_movie_by_name` 递归里拿出，统一在 `__get_media_info` 上层用 modifiedname 处理并联动缓存键；(2) `MetaBase` 新增 `set_name(modifiedname)` 用于命中后回写修正名。
- **核心逻辑**：
  - `__get_media_info`:
    ```
    if meta_info.type in (MOVIE, UNKNOWN):
        ix = meta_info.get_name().find(' ')
        if ix > 0 and name[:ix].isdigit():
            modifiedname = name[ix+1:]
    media_key = __make_cache_key(meta_info)
    if cache and not meta.get_meta_data_by_key(media_key) and modifiedname:
        media_key = __make_cache_key(meta_info, modifiedname=modifiedname)
        use_modifiedname = True
    ```
    命中后 `meta_info.set_name(modifiedname)`。
  - `_base.py`:
    ```
    def set_name(self, modifiedname):
        if cn_name and is_all_chinese(cn_name): cn_name = modifiedname
        elif en_name: en_name = modifiedname
        elif cn_name: cn_name = modifiedname
    ```
  - 移除 `7bbdf168` 在 `__search_movie_by_name` 里加的 `fmnspaceindex` 递归分支。
- **迁移关注点**：v4 的"标题净化→修正名→缓存键"应在 `media_info_service.py` 与缓存层保留这套联动；`set_name` 等价方法需在新 MetaBase 上保留。

### 4297c804 fix ep and name have digit qst
- **改动文件**：`app/media/meta/metavideo.py`
- **设计目标**：(1) `original_title` 局部变量被用于 resource_team/customization/DIY 判定，但 `original_title = title` 在某些路径下是已被 `rev_title` 处理过的串，改统一用 `self.org_string`；(2) `total_episodes > 2` 单文件多集误判过滤只看 `fileflag`，遇到种子里 `EP01 02` 这种"显式集范围"会漏过，加入正则识别。
- **核心逻辑**：
  ```
  ... re.findall(r'-D[Ii]Y@', self.org_string)
  ... ReleaseGroupsMatcher().match(title=self.org_string)
  ... CustomizationMatcher().match(title=self.org_string)
  ...
  if re.search(r'[ \.\d]EP?\d{1,3}[ \.]\d{1,3}[ \.]', self.org_string, re.IGNORECASE) \
        or (self.fileflag and self.total_episodes > 2):
      self.end_episode = None
      self.total_episodes = 1
  ```
- **迁移关注点**：v4 MetaVideo 等价类需保留：资源组/自定义/DIY 匹配都基于 `org_string` 而非本地变量；"集范围正则 `EP?\d{1,3}[ \.]\d{1,3}`"判断"显式集范围"是硬规则，确认 v4 是否已有等价集范围解析。

### 26e7bde4 修正媒体元数据识别错误将作品名中的 Season 去除的 bug
- **改动文件**：`app/media/meta/metavideo.py`
- **设计目标**：英文名以 "Season" 结尾（`The Long Season`、`Cherry Season`）后跟 S01/年份时，原代码把季/年份剥离时把 "Season" 也归入季描述剥掉，导致标题被截成 `The Long`。本提交识别"Season 结尾"为"标题保留"信号。
- **核心逻辑**：
  - 把原"季/集/资源类型/分辨率"合并的 elif 拆分，季单独一支：
    ```
    elif re.search(self._season_re, token, re.IGNORECASE):
        if self.en_name and re.search(r"SEASON$", self.en_name, re.IGNORECASE):
            self.en_name += ' '
        self._stop_name_flag = True
        return
    ```
  - 处理年份时同理保留 Season：
    ```
    elif self.en_name and re.search(r"SEASON$", self.en_name, re.IGNORECASE):
        self.en_name += ' '
    self.year = token
    ```
  - `" %s" % (self.en_name.strip(), self.year)` 用 strip 防止空格累积。
- **示例**：`The Long Season 2023 …` 识别为 `The Long Season (2023)` 而非 `The Long (2023)`。
- **迁移关注点**：v4 MetaVideo 等价类是否在做季/年份剥离前检查 en_name 结尾词。务必验证 `* Season S01 ...` 与 `* Season 2023` 两类样例。

### 8e7dadc2 补充名称识别修改单元测试情况
- **改动文件**：`app/media/meta/metavideo.py`、`tests/cases/meta_cases.py`
- **设计目标**：给 `26e7bde4` 补回归用例。
- **核心逻辑**：`meta_cases` 列表头部新增两条：
  - `The Long Season 2017 2160p WEB-DL H265 AAC-XXX` → 电影，en_name="The Long Season"，year="2017"。
  - `Cherry Season S01 2014 2160p WEB-DL H265 AAC-XXX` → 电视剧，en_name="Cherry Season"，season="S01"，year="2014"。
- **迁移关注点**：v4 元数据测试集应继承这两个 case；pytest 体系需改写签名。**必须保留**。

### 170d072c 历史记录更新正则搜索方式
- **改动文件**：`app/helper/db_helper.py`、`web/templates/rename/history.html`
- **设计目标**：历史记录搜索默认 `LIKE %kw%`，本提交新增约定：搜索串首尾都被 `/` 包裹时（如 `/a|b/`）按正则匹配。
- **核心逻辑**：`DbHelper.get_transfer_history`:
  ```
  if search[0] == search[-1] == '/':
      search = search[1:-1]
      ... .filter(SOURCE_FILENAME.regexp_match(search) | TITLE.regexp_match(search)) ...
  else:
      search = f"%{search}%"
      ... .like(search) ...
  ```
  模板搜索框加 `placeholder="两头加/支持正则搜索，如/a|b/"`。
- **迁移关注点**：v4 若换 SQLAlchemy/不同 ORM，注意 `regexp_match` 在 SQLite/MySQL 上的可用性（SQLite 需自定义 REGEXP 函数）。

### 01937eb6 手动识别和历史记录加入动态搜索
- **改动文件**：`web/templates/rename/history.html`、`web/templates/rename/unidentification.html`
- **设计目标**：搜索框从"回车才搜"升级为"输入停顿后自动搜"。
- **核心逻辑**：
  ```
  function gosearch(){ navmenu("...?s=" + keyword + "&pagenum=" + pagenum); }
  var searchkeytimeout = null;
  $('#search_word').bind({
      keypress: function(e){ if (e.keyCode == "13") gosearch(); },
      keyup:    function(e){ clearTimeout(searchkeytimeout);
                            searchkeytimeout = setTimeout(gosearch, 1000); }
  });
  ```
- **迁移关注点**：v4 前端用 input 事件 debounce（vue-use `useDebounceFn`），后端无需改动。

### 28a24f82 减少动态搜索延时
- **改动文件**：`web/templates/rename/history.html`、`web/templates/rename/unidentification.html`
- **设计目标**：把 `01937eb6` 的 1000ms 防抖降到 500ms。
- **核心逻辑**：两处页面同改 `setTimeout(gosearch, 1000)` → `setTimeout(gosearch, 500)`。
- **迁移关注点**：v4 拖到公共 composable，500ms 是合理默认。

### 4bd87041 历史记录添加每页条数 + fix
- **改动文件**：`web/action.py`、`web/templates/rename/history.html`、`web/templates/rename/unidentification.html`
- **设计目标**：历史记录页补齐与未识别页同款"每页条数下拉 + 路径失效标记/批量选择"，并修分页链接漏带 pagenum 的 bug。
- **核心逻辑**：
  - `WebAction.get_transfer_history` 给每条记录加：
    ```
    isexists_source_path = os.path.exists(history.SOURCE_PATH) if history.SOURCE_PATH else True
    isexists_dest_path   = os.path.exists(history.DEST_PATH)   if history.DEST_PATH   else True
    ```
  - history.html：新增"选择无效项"下拉（三类：仅源无效 1 / 仅媒体库无效 2 / 均无效 3）；checkbox `data-notexists="1/2/3"`；每页条数下拉 `(30,50,100,200,300,500,1000)`；分页链接全部带 pagenum。
  - unidentification.html 仅修分页链接漏带 pagenum。
- **迁移关注点**：v4 历史 API 需返回源/目标路径的 isexists；前端"每页条数 + 失效项批量选择"需在新历史组件里实现。

### B 组主要贡献要点汇总
- 标题序号前缀处理：剥离开头纯数字段，生成 modifiedname 用作二次搜索与缓存键联动，命中后用 `set_name` 回写修正名。
- 标题结尾重复年份处理：剥掉与 `meta_info.year` 重复的年份尾巴。
- 无年份兜底：搜索前临时把 year 填为当年。
- 中文标题二次纯英文匹配：全链 `onlyen` 参数，中文名为主搜不到时跳过中文 token 只用英文重跑。
- 中文 token 剥离季数描述词：正则 `[全共第][0-9一二三四五六七八九十]+季全?`。
- 中英混合标题的英文片段归属判定。
- Season 在标题里被误剥离的修复（保留两条 pytest case）。
- 集范围正则 + 资源组/DIY 匹配基于 `org_string`。
- 历史记录/未识别页体验：每页条数 + 路径失效项可视化与三类批量勾选 + 正则搜索 + 500ms 防抖 + 修 `PageNum` 误传 bug。

### B 组文件迁移对照（dev → v4 预期落点）
| dev 旧路径 | v4 预期落点 |
|---|---|
| `app/media/media.py` | `src/app/services/media_info_service.py` + `src/app/media/` 下搜索调度 |
| `app/media/meta/metavideo.py` | `src/app/media/` 下的视频 Meta 类 |
| `app/media/meta/_base.py` | v4 MetaBase 等价类（`set_name`、`onlyen`） |
| `app/media/meta/metainfo.py` / `metaanime.py` | v4 MetaInfo 工厂与动漫 Meta（`onlyen` 透传） |
| `app/helper/db_helper.py` | v4 历史记录查询层 |
| `web/action.py` / `web/main.py` | v4 history/unknown list API |
| `web/templates/rename/history.html` / `unidentification.html` | v4 前端组件 |
| `web/static/js/util.js` | v4 前端公共工具 |
| `tests/cases/meta_cases.py` | v4 元数据测试集 |

---

## 三、C 组 — 订阅/RSS（3 个提交）

### d4f22248 增加添加种时自动更新电影订阅信息
- **改动文件**：`app/indexer/client/builtin.py`(+1/-1)、`app/subscribe.py`(+32)、`web/action.py`(+10)
- **设计目标**：Web 手动添加种子下载成功后，自动识别该媒体是否对应已有订阅，命中则按"洗版/普通"分别更新订阅状态，省去手动确认完成。
- **核心逻辑**：
  - 新增方法 `Subscribe.update_subscribe(self, meta_info)`：取 `mtype/title/year/season`，剧集 `season` 存在则 `year=None`，用 `self.get_subscribe_id(...)` 反查 `rssid`。
  - 命中后电影走 `get_subscribe_movies(rid=rssid)` 遍历：
    - `over_edition` 为真 → `update_subscribe_over_edition(rtype=MediaType.MOVIE, rssid=rssid, media=meta_info)`
    - 否则 → `finish_rss_subscribe(rssid=rssid, media=meta_info)`
  - 剧集留 TODO。
  - 触发点：`web/action.py::add_torrent/download` 手动下载入口 `ret` 为真后调。
  - 顺带把 builtin spider 超时 30s→90s。
- **v4 现状**：v4 已重构为 `src/app/services/subscribe/management/`：`UpdateService.update_rss_subscribe` 是"按订阅 ID 更新字段"语义，**不是** sjh00 这里的"按 media 反查并自动 finish/over_edition"。`finish_service.finish_rss_subscribe`/`service.update_subscribe_over_edition` 能力已具备。但 v4 download 链路 (`download_service`、`handlers`、`download_core`) 未发现"手动下载成功后回写订阅状态"的连接点。
- **结论**：部分已实现，**手下载回写电影订阅链路需补**；剧集 TODO 可在新 base 上一并填实。

### b69d1e54 增加 rss 订阅限定小时
- **改动文件**：`app/helper/rss_helper.py`(+19)、`app/rss.py`(+6)、`app/sites/sites.py`(+1)、`web/templates/site/site.html`(+22)、`web/static/css/tabler.min.css`(+1)
- **设计目标**：单站点配置"只订阅最近 N 小时内发布的种子"阈值，过滤过老 RSS 条目（刷流不受限）。
- **核心逻辑**：
  - 新增 `RssHelper.is_rss_inhour(rss_pubdate, site_withinhour) -> bool`：`rss_pubdate` 空 → `False`；`site_withinhour` 非正整数 → `True`；否则 `rss_pubdate + timedelta(hours=site_withinhour) >= datetime.now()`。
  - `app/rss.py`：从 `site_info` 取 `withinhour`，article 的 `pubdate` 不在窗口则日志并 `continue`。
  - 站点配置侧字段名 `withinhour`（存 site_note，UI `id=site_withinhour` type=number）。
- **v4 现状**：v4 RSS 链路 `rss_processor.py` 仅解析 `pubDate` 为时间戳保存，全 src 无 `withinhour/is_rss_inhour/限定小时` 命中。**未迁移**。
- **结论**：可在 v4 站点配置 + RSS processor 阶段补一个发布时间窗口过滤；UI 字段同名 `withinhour` 即可。

### 27096553 修改订阅里站点搜索逻辑
- **改动文件**：`app/subscribe.py`、`web/static/js/functions.js`、`web/templates/rss/user_rss.html`
- **设计目标**：允许订阅"只走 RSS、不进行站点搜索"——通过把 `search_sites` 设为 `["#dontuse"]` 哨兵表达该语义。
- **核心逻辑**：
  - 前端：用户搜索站点选空时写入 `["#dontuse"]`；回显时若已为 `["#dontuse"]` 不当作"全选"。
  - 后端：`get_subscribe_movies/tvs` 加守卫 `if search_sites != ["#dontuse"]: ...`；`search_target_*` 循环跳过条件扩为 `fuzzy_match or search_sites == ["#dontuse"]`。
- **v4 现状**：`base_search.py` 仅有 `fuzzy_match` 跳过，无 `#dontuse` 哨兵。v4 用 `SubscribeState` 状态机控制是否触发搜索，可能以"状态"形式承担了"不搜索"语义。
- **结论**：功能近似但实现不同，按 v4 架构另行映射，**不必照搬 `#dontuse` 字面量**。

### C 组主要贡献要点汇总
- 手动下载成功后反查订阅并自动 finish/over_edition；spider 超时 30s→90s。
- 站点级 RSS 限定小时（`withinhour` + `is_rss_inhour`，刷流不受限）。
- 「只订阅不搜索」哨兵 `["#dontuse"]`（前端+后端守卫）。

---

## 四、D 组 — 文件名/URL 解析 + Bonus transfer（3 个提交）

### f00e65cf fix tv file name with 'of'
- **改动文件**：`app/media/meta/metavideo.py`(+3)
- **设计目标**：修电视剧文件名含 `of`（如 `S01 of ShowName` 之类尾随 of）被吞入剧名/季解析的边界问题。
- **核心逻辑**：`__init_name` 内 token 处理新增：
  ```
  elif token.upper() == "OF":
      self._last_token_type = "OF"
      self._continue_flag = False
  ```
  即把 `of` 视作终止名称追加的 token。
- **v4 现状**：v4 `src/app/media/parser/video/name_parser.py::init_name` 仅有 `_name_se_words`/`AKA`，**没有** `OF` 分支。若 v4 真实文件名仍含 `of` 会复现该问题，**建议迁移**。

### abbd6617 fix url with '+'
- **改动文件**：`web/main.py`(+8)、两个 html 模板
- **设计目标**：文件路径含 `+` 在 `navmenu("mediafile?dir=...")` 跳转时被异常解析，需对 URL 多重编码。
- **核心逻辑**：新增 Jinja 模板过滤器：
  ```
  @App.template_filter('urlquote')
  def urlencode_filter(text):
      text = urllib.parse.quote(text)
      return Markup(text)
  ```
  模板对路径做 `| urlquote | urlquote` 双重编码。
- **v4 现状**：v4 前端已是 SPA，无 Jinja 模板过滤器；路径参数由前端 API 客户端 `encodeURIComponent` 负责。
- **结论**：实现不可移植，需求（路径含 `+`/特殊字符在记录页跳转里被正确编码）应以 v4 前端 URL 编码姿态替代。验证 v4 历史页跳转 `encodeURIComponent(dir)` 是否已覆盖。

### 04edcb82 add bonus transfer & fix（BONUS/花絮转移整套能力）
- **改动文件**：
  - `app/filetransfer.py`(+152/-43) — 新增 `__transfer_extra_dir`、转移主循环增加"额外内容目录"识别，`__transfer_existing` 加 `isextras` 分支
  - `app/media/media.py`(+19/-8) — `Media` 扫描阶段新增 `PathUtils.is_extras`/`get_extras_dir` 跳过与 note 标记
  - `app/media/meta/metavideo.py`(+3/-1) — title 预处理剔除 `BONUS.DISC` 等后缀；`_episode_re` 调整为 `S\d{2}E?P?(\d{2,4})`
  - `app/utils/path_utils.py`(+33/-1) — 新增 `is_extras` / `get_extras_dir` 静态方法
- **设计目标**：识别"额外内容/花絮目录"（`BONUS.DISC`、`behind the scenes`/`deleted scenes`/`interviews`/`samples`/`shorts`/`featurettes`/`clips`），转移时按 `extras/` 季-子目录归档；跳过 TMDB 识别/转移历史/NFO&海报/字幕事件，避免花絮被误当未识别媒体或污染主目录。
- **核心逻辑**：
  - `app/utils/path_utils.py` 新增：
    - `PathUtils.is_extras(path)`：
      - 目录名匹配 `.+?[\._ ]BONUS[\._ ]DISC|behind the scenes$|deleted scenes$|interviews$|scenes$|samples$|shorts$|featurettes$|clips$`
      - 文件名匹配 `.+?[\._ ]BONUS[\._ ]DISC[\._ ]|.+?SP?\d{1,2}\.extras\.\d{2,}|.+?\.extras-\d+\.`
    - `PathUtils.get_extras_dir(path)`：取父目录再按目录名同款正则判定
  - `app/media/media.py`：
    - 非目录文件先过 `get_bluray_dir` / `get_extras_dir` 跳过其下子文件
    - 每个文件 `isextras = PathUtils.is_extras(file_path)`；若 `isextras and len(file_name)<12`：`file_name=parent_name`、`parent_name=parent_parent_name`（用父级目录做识别）
    - 识别后 `meta_info.note['is_extras'] = True`（**关键 note 字段名**）
  - `app/filetransfer.py`：
    - 新增 `__transfer_extra_dir(self, file_path, new_path, rmt_mode)`（与 `__transfer_bluray_dir` 同构）
    - 主循环 `extra_dir = PathUtils.get_extras_dir(in_path)` 优先判断
    - `__transfer_existing` 新增：`isextras = 'is_extras' in media.note and media.note['is_extras']`，命中时电影 `dir_name = os.path.join(dir_name, 'extras')`，剧集 `season_name = 'extras'`，文件名取 `os.path.splitext(media.org_string or "")[0]`
    - `if not isextras:` 守卫包围 `insert_transfer_history` / `scraper.gen_scraper_files` / `EventSubtitleDownload`
    - `media.org_string = file_name` 命中花絮时回填文件名给路径解析用
  - `metavideo.py`：
    - 标题预处理新增 `title = re.sub(r"[\._]BONUS[\._]DISC|\.extras-\d+", "", title, count=1, re.IGNORECASE)`
    - `_episode_re`: `S\d{2}EP?(\d{2,4})` → `S\d{2}E?P?(\d{2,4})`（兼容 `S01P03` 花絮片段编号）
- **v4 现状**：v4 转移逻辑在 `src/app/services/transfer/`（`filetransfer_service.py`、`path_resolver.py`、`existence_checker.py`、`history_manager.py`、`handlers.py`）。`src/app/utils/path_utils.py` grep `extras/bonus/is_extras` 无命中。`filetransfer_service.py`、`path_resolver.py` 同 grep 无命中。`src/app/media/parser/regex.py::_episode_re` 仍是旧式 `S\d{2}EP?(\d{2,4})`，**没有** `E?P?` 调整。`name_parser.init_name` 无 `OF` 分支；标题预处理无 `BONUS.DISC`/`.extras-` 剔除。
- **结论**：**BONUS/花絮转移整套功能在 v4 未迁移**——包括 `is_extras`/`get_extras_dir`、`media.note['is_extras']`、转移时归 `extras/`、跳过 scraper/history/字幕，以及 metavideo 的两处正则/OF 修复。建议作为完整功能 rip 重写到 v4 的 `services/transfer/` 体系。

### D 组主要贡献要点汇总
- 修复 TV 文件名 `of` token 异常：`_last_token_type="OF"` 且 `_continue_flag=False`。
- URL 含 `+`：Jinja `urlquote` 双重编码（v4 用前端 `encodeURIComponent` 等价替代）。
- BONUS/花絮目录整套转移能力：
  - `PathUtils.is_extras`/`get_extras_dir` 多模式识别
  - `Media` 扫描跳过花絮子文件、`note['is_extras']` 透传
  - `__transfer_extra_dir`；电影归 `<主目录>/extras/`、剧集 `season_name='extras'`
  - 命中花絮时不写 transfer_history/不生成 NFO/不发 `SubtitleDownload` 事件
  - metavideo 剔除 `BONUS.DISC`/`.extras-` 并放宽 `_episode_re` 为 `S\d{2}E?P?(\d{2,4})`

### D 组迁移取舍建议
- `b69d1e54`、`04edcb82`、`f00e65cf`、`d4f22248`：v4 base 未发现对应实现，应作为候选项优先迁移。
- `27096553`（`#dontuse` 哨兵）、`abbd6617`（Jinja urlquote）：v4 因状态机/前端框架不同等价或失效，按 v4 架构另行映射。

---

## 五、E 组 — 过滤规则指定原始语言（最高优先级，rebase 后必须补加）

### 1. 设计目标
为过滤规则新增「指定原始语言」维度：规则中指定 TMDB 原始语言代码（zh/en/ja/ko/fr/de/ru/hi/other 或留空=全部），过滤引擎判断种子是否合规前，先用种子标题查/取缓存 TMDB 信息，得到条目 `original_language`，按代码前两位匹配；指定 `other` 表示「不在已知列表内的语言」。让用户能针对「只想下中文原始语言」「只想下英语原盘」等做更精细规则。

### 2. 字段与 schema
- ORM：`CONFIGFILTERRULES.ORIGINAL_LANGUAGE = Column(Text)` —— 存 `zh/en/ja/ko/fr/de/ru/hi/other` 或 ''
- dict：`rule_info.get("original_language")`；API 入参 `rule_original_language`
- 前端控件：`#rule_original_language`（select，含"全部"+9 个语言项）
- 集合常量：`self._language_options = [m.value for m in ModuleConf.DISCOVER_FILTER_CONF["tmdb_movie"]["with_original_language"]["options"] if value and value != 'other']`
- `scripts/sqls/init_filter.sql`：在 INCLUDE 列前插入 `ORIGINAL_LANGUAGE`，全部预置规则值为 ''
- `scripts/sqls/update_filterrule_addorilang.sql` 完整内容：
  ```sql
  ALTER TABLE main.CONFIG_FILTER_RULES ADD ORIGINAL_LANGUAGE TEXT;
  UPDATE main.CONFIG_FILTER_RULES SET ORIGINAL_LANGUAGE = '' WHERE 1;
  ```

### 3. 后端核心逻辑

#### a. `app/filter.py`（Filter 类）
- 新增成员 `self._language_options`
- `get_filter_rule()` 转 dict 加入 `"original_language": rule.ORIGINAL_LANGUAGE or ''`
- `check_rules` 在 include 之前、order_seq 之后插入：
  ```python
  rule_original_language = filter_info.get('original_language')
  if rule_original_language and rule_match:
      meta_original_language = meta_info.original_language
      if meta_original_language:
          meta_original_language = meta_original_language.strip()
          if rule_original_language == 'other':
              if meta_original_language[:2] in self._language_options:
                  rule_match = False
          elif rule_original_language[:2] != meta_original_language[:2]:
              rule_match = False
  ```
  关键语义：
  1) 规则未填语言 → 跳过
  2) 规则填了但 meta 无 `original_language` → 不阻断
  3) `other` → 命中已知列表视为不匹配
  4) 其他语言 → 比较前两位字符
- `check_torrent_filter` 不命中信息追加 `原始语言：{meta_info.original_language}`

#### b. 调用方传参（均依赖 `meta_info.original_language`）
- `app/indexer/client/_base.py`：`check_torrent_filter` 之前先 `get_cache_info(meta_info)`；缓存 `id` 存在且 `original_language` 非空 → 赋值；否则 `get_media_info(title=..., subtitle=..., mtype=...)` 重新查 TMDB 并赋值。
- `app/rss.py`：缓存命中条件由 `cache_info.get("id")` 改为 `cache_info.get("id") and cache_info.get("original_language") is not None`；显式 `media_info.original_language = cache_info.get("original_language")`。
- `app/rsschecker.py`：同上两处识别改造。
- `app/brushtask.py`：新增 `self.media = Media()`、`self._language_options`，选种循环里：
  ```python
  rule_original_language = rss_rule.get("original_language")
  if rule_original_language:
      media_info = MetaInfo(title=title)
      cache_info = self.media.get_cache_info(media_info)
      if cache_info.get("id"):
          meta_original_language = cache_info.get("original_language")
      else:
          media_info = self.media.get_media_info(title=title)
          if media_info and media_info.original_language:
              meta_original_language = media_info.original_language
      if meta_original_language:
          # other / 前两位比较；不匹配 return False
  ```
  注意 brushtask 把 `original_language` 直接做成 `rss_rule` 字典字段，不走 Filter 类。

#### c. `app/media/media.py` + `app/helper/meta_helper.py`
- `media.py` 生成 TMDB 缓存 dict 时新增 `"original_language": file_media_info.get("original_language")` 字段（来源 TMDB 详情接口）。
- `meta_helper.py::insert_media_cache` 把 `original_language` 写入缓存 JSON。

#### d. Web API 入口
- `web/apiv1.py::FilterRuleUpdate`：`parser.add_argument('rule_original_language', type=str, help='指定原始语言', location='form')`
- `web/action.py`：
  1) `add_or_edit_filterrule`：把 `data.get("rule_original_language")` 提出/传入 `item`
  2) `get_filterrules`：每条 rule 加 `"original_language": rule.ORIGINAL_LANGUAGE`；分享/导出同加
  3) `match_filter_rule`：title + subtitle 后规则通过则 `Media().get_media_info(title=title)` 拿到 `original_language` 赋给 `meta_info` 二次过滤
  4) `get_filterrules` 解析 `init_filter.sql`：因新列插 INCLUDE 前，`rule.split(",")` 偏移：`rule[4]` → ORIGINAL_LANGUAGE、include 改 `rule[5]`、exclude 改 `rule[6]`（**关键，否则恢复规则解析错位**）

### 4. 前端 UI（v3 实现）
`web/templates/setting/filterrule.html`：
- 顶部 Jinja：`{% with language_dict = {"zh":"中文","en":"英语","ja":"日语","ko":"韩语","fr":"法语","de":"德语","ru":"俄语","hi":"印地语","other":"其他"} %}`
- 规则列表项「促销」徽章后追加「原始语言」徽章（仅 `Rule.original_language` 存在时显示）
- 编辑区把"优先级 `col-lg-6`"改 `col-lg-3`，旁加 `col-lg-3` 语言 select（id `rule_original_language`，「全部」+9 项）
- JS：`show_filterrule_modal` 重置 `val('')`；加载详情 `val(ret.info.original_language)`；提交参数对象加 `rule_original_language: ...val()`

### 5. v4 现状对照（已再次确认）
- `src/app/services/filter_service.py`（526 行）：
  - `get_rules` 字段：`id, group, name, pri, include, exclude, size, free, free_text` —— **无 `original_language`**
  - `FilterRuleEngine.check_rules`、`check_torrent_filter` 均无 original_language 分支
  - `import_filter_group`/`share_filter_group` 不带语言字段
  - `test_rule` 不查 TMDB
- `src/app/indexer/core/filter_engine.py`（`IndexerFilterEngine`）：`check_torrent_filter`/`check_rules` 无 original_language 分支
- `src/app/indexer/core/result_filter.py::_get_rules`：dict 字段 `include, exclude, size, free, pri`，不带 original_language
- `src/app/services/subscribe/matcher.py` 第 184 行起：手写"重建规则 dict"调用 `FilterRuleEngine`（必须同步加 `original_language`，否则即使规则库保存了语言，订阅这条路径仍不生效）
- DB schema：`src/app/db/models/config.py::CONFIGFILTERRULES` 列 `ID, GROUP_ID, ROLE_NAME, PRIORITY, INCLUDE, EXCLUDE, SIZE_LIMIT, NOTE` —— 无 `ORIGINAL_LANGUAGE`
- `src/app/db/data/init_filter.sql`：列顺序同上，预置规则无语言列
- alembic 全部 migration（约 50 个 versions）无任何给 `CONFIG_FILTER_RULES` 加 `ORIGINAL_LANGUAGE` 列（`5ec25bdc842f_split_rule_id_columns.py`、`f8a9b0c1d2e3_rename_rss_tables_to_subscribe_tables.py` 只动 ForeignKey/索引/表重命名）
- `src/app/domain/entities/config.py::FilterRuleEntity`：字段 `id, group_id, name, include, exclude, note, priority, create_time, update_time` —— 无 original_language
- `src/app/db/repositories/config_repo_adapter.py::FilterRuleRepositoryAdapter.insert`：签名 `(group_id, name, include, exclude, note, priority)`，需补字段映射。
- 媒体信息 v4 利好：`src/app/media/models.py::MediaInfo` 已有 `original_language: str | None`，`set_tmdb_info` line 459 `self.original_language = info.get("original_language")`。**TMDB 识别流程元数据已就绪**，只需让「过滤发现」与「规则侧保存读取」对接。
- BRUSH/RSS：`SITEBRUSHRULE.RSS_RULE` 是 `Text`（JSON 字符串），`src/app/domain/engine/brush_rule_engine.py::check_rss_rule` dict-style `rule.get("size"/"include"/"exclude"/"free"/"hr"/"peercount"/"pubdate"/"exclude_subscribe"/"category_*"/"label_*")`，无 `original_language` 键；v4 刷流独立成 `brush/rss_checker.py`/`scheduler.py`/`torrent_lifecycle.py`
- 模块配置：v4 不存在 `ModuleConf.DISCOVER_FILTER_CONF`（`tmdb_movie`/`with_original_language`/`DISCOVER_FILTER` 全 0 命中），`_language_options` 必须改写为本地常量
- 前端：v4 仓库为纯后端（grep 任何 `.html/.vue/.tsx` 均 0 命中），过滤规则/刷流规则页在外部前端项目；后端经 `src/api/routers/filter.py` 等 API 暴露

### 6. 迁移到 v4 的实施要点（精确路径）

**A. DB schema（必须走 alembic，不能直接改 `init_filter.sql`）**
- 新增 `alembic/versions/xxxx_add_original_language_to_filter_rules.py`：
  - `upgrade()`: `op.batch_alter_table("CONFIG_FILTER_RULES")` 加 `sa.Column("ORIGINAL_LANGUAGE", sa.Text, nullable=True)`；随后 `UPDATE` backfill `''`（参考同目录 `5ec25bdc842f_split_rule_id_columns.py` 的 `batch_op.add_column` 写法，SQLite 兼容必须 `batch_alter_table`）
  - `downgrade()`: 反向 `drop_column`
- `init_filter.sql` 可不动（新库由 alembic init 之后跑 trivial migration 完成）；若希望预置规则默认语言标签，可选加 NOTE 之前的列，不影响现有解析顺序。

**B. ORM 模型**
- `src/app/db/models/config.py::CONFIGFILTERRULES` 加 `ORIGINAL_LANGUAGE: Mapped[str | None] = mapped_column(Text, nullable=True)`

**C. Entity / Adapter**
- `src/app/domain/entities/config.py::FilterRuleEntity` 加 `original_language: str | None`，`from_orm` `original_language=orm_model.ORIGINAL_LANGUAGE or ""`
- `src/app/db/repositories/config_repo_adapter.py::FilterRuleRepositoryAdapter.insert` 透传 `item["original_language"]`，检查 `src/app/db/repositories/config_repository.py::insert_filter_rule` 是否做白名单映射，如需补 `ORIGINAL_LANGUAGE` 列写入

**D. 服务层（三处必须同步，否则"保存但实效"）**
- `src/app/services/filter_service.py`：
  - `get_rules` 每条 `rule_info` 加 `"original_language": rule.ORIGINAL_LANGUAGE or ''`
  - `FilterRuleEngine.check_rules` 在 include 前加 sjh00 判断段；类级新增常量 `_LANGUAGE_OPTIONS = {"zh","en","ja","ko","fr","de","ru","hi"}`（与前端一致，`other` 不进集合）
  - `check_torrent_filter` 不命中信息追加 `原始语言：{meta_info.original_language or "未知"}`
  - `import_filter_group`/`share_filter_group` 输入输出 dict 加 `original_language`
  - `test_rule(title, subtitle, size, rulegroup)`：先 `meta_info(title, subtitle)` 跑一次；若命中且规则组中存在任意 `original_language` 非空，注入 `Media` 依赖二查 TMDB 拿到 `original_language` 后二次过滤返回；"未填语言"时复用旧流程不增负担
- `src/app/indexer/core/filter_engine.py::IndexerFilterEngine.check_rules` 加同段判断（v4 索引器搜索路径实际在用 `IndexerFilterEngine`，**双写必须**）
- `_LANGUAGE_OPTIONS` 建议提到 `app/core/` 或 `app/domain/` 公共常量避免重复

**E. 注入「原始语言」元数据（无需新增 TMDB 查询，因 v4 已就绪）**
- `src/app/indexer/core/result_filter.py::match_filter`（命中 TMDB 后第三阶段）补"规则含 original_language 非空则二次过滤"；`local_filter` 第一阶段（无 TMDB）**不做语言过滤**——避免大量无语言数据种子误伤
- `src/app/services/subscribe/matcher.py` 第 184–225 行重建规则 dict 同步加 `original_language=e.original_language`（单值字符串，不涉及 split 差异）；订阅路径才会生效

**F. BRUSH / RSS 选种**
- `SITEBRUSHRULE.RSS_RULE` 已是 Text JSON，无需 schema 变化，直接加 `original_language` 键
- `src/app/domain/engine/brush_rule_engine.py::check_rss_rule` 的 `rule_checks` dict 新增：
  ```python
  "original_language": lambda rv: cls._match_original_language(media_info, rv),
  ```
  新增 `_match_original_language(media_info, rule_value)` 实现 other/前两位逻辑；`media_info.original_language` 为空按 sjh00 守卫 "不阻断"（return True）
- v4 `MediaInfo.original_language` 由 `set_tmdb_info` 自动赋值，订阅相关不再需手动从 `cache_info` 读

**G. API 路由**
- `src/api/routers/filter.py::AddFilterRuleRequest` 加 `rule_original_language: str | None = None`
- `add_filterrule` 端点 `item` dict 加 `"original_language": req.rule_original_language`
- `RuleTestRequest` 不需要新字段；若希望便于调试可在 `data` 返回 `original_language` 字段

**H. 前端**
- 本仓库无前端文件，需在外部 nexus-media 团队的另一前端项目"过滤规则"设置页与"刷流任务"规则编辑组件各加语言下拉
- 控件 id 建议保持 `rule_original_language`，下拉值与后端常量一致；刷流侧字段名 `original_language`；规则渲染徽章按 sjh00 设计

### 7. 迁移风险点
1. **三处规则匹配需同步**：`FilterRuleEngine`、`IndexerFilterEngine`、`subscribe/matcher.py` 三处必须同步补 `original_language`，移除任一即留下"规则保存了但过滤不生效"的隐性 bug。
2. alembic 必须 `batch_alter_table` 兼容 SQLite；为已存在规则 backfill `''`，避免 NULL/空字符串混用。
3. indexer `local_filter` 第一阶段无 TMDB，`original_language` 通常为空；若把语言判断放 `check_rules` 静态方法，必须保证"rule 填了但 meta 为空"时不阻断（sjh00 原守卫），否则大量无语言数据种子被误杀。
4. v4 没有 `ModuleConf.DISCOVER_FILTER_CONF`，`_language_options` 列表来源必须重新定义并与前端 `language_dict` 严格对齐。
5. `test_rule` 在 v4 当前不查 TMDB；做二次回查需注入 `Media` 服务并控制 TMDB 速率；可选改造保留 v4 轻量。
6. 前端位于独立仓——本仓库后端改好后，前端若不在同 PR 提交会出现"后端可保存但 UI 看不见"的过期状态。
7. v4 刷流 `RSS_RULE` 是 JSON；新字段加入时兼容旧 JSON（缺 key 默认 `''`，按守卫跳过），否则老刷流任务会全判不匹配导致刷流停止。
8. `share_filter_group`/`import_filter_group` 字段对齐：分享出去的规则组必须带语言字段；导入端必须容错（缺 `original_language` 键默认 `''`，不要 KeyError）。

### E 组一句话贡献要点
为过滤规则增加「指定 TMDB 原始语言」维度（zh/en/ja/ko/fr/de/ru/hi/other），可在 indexer / 订阅 / 自定义 RSS / 刷流各路径上对接已有 `media_info.original_language`，按语言代码前两位或「其他」做规则匹配，让用户能按"原始语言"精细化筛选资源。

---

## 六、G 组 — 模糊 fix 与文档标记（24+ 个，rebase 后按需逐个 git show）

未提炼说明，列出 hash 与主题供后续按需查看。rebase 后如需逐项检查可 `git show <hash>` 一一比对。

### 模糊 fix（无描述）
`36d04dab` `90747a63` `eae8811c` `e93cdb4c` `605f515c` `18059d2f` `dadf1dd5` `b0b52d65` `12dde990` `5da62848` `201bde3e` `ae2be3b3` `f44645b4` `696383a0` `eecc792d` `0a4b218c` `61eb3533` `db02e2be` `3ff1e9f5` `a7ea1fb4` `959bade3` `e56fe957` `15947c9c` `aa8425ea`(change) `1ea76d81`(update)

这些是 2023-04~08 占位 fix，多见于 dev 同区域、与已识别主题提交相邻；大概率被 v4 的整体重构自然覆盖，默认不沿用，仅当某条恰好对 v4 现状仍问题时再单独评估。

### 文档 / 历史标记（rebase 时丢弃）
- `70f26400` Update index.js
- `853bc46f` / `96d77174` / `f1ee66b2` Update README.md
- `03a04e0e` ori 3.2.3（快照标记）
- `ed6e5d2f` Merge '3.2.3' into dev（历史标记，author=sjh00）

---

## 七、下一步

- 实际 rebase 动作另开一轮 plan 输出（命令序列、冲突预案、E 组补加顺序、验证用例）。
- rebase 后逐项检查 v4 是否已实现或更好：
  - 已实现/v4 更好 → 丢弃 sjh00 老代码
  - 未实现且 sjh00 更好 → 按本文档「迁移关注点」逐项手工迁移到 v4 新结构
- E 组（过滤规则原始语言）按本文档第五节完整实施要点补加。

### 推荐验证用例集（迁移完成后回归）
1. `The Long Season 2017 2160p WEB-DL H265 AAC-XXX` → 电影、en_name=The Long Season、year=2017
2. `Cherry Season S01 2014 2160p WEB-DL H265 AAC-XXX` → 电视剧、season=S01、year=2014
3. `Movie Name 电影名 S01 ...` → cn_name="Movie Name 电影名"（不掉英文片头）
4. `1 Movie Title 2023` → 标题序号剥离为 `Movie Title`，缓存键联动
5. 含中文标题种子 TMDB 命中率为 0 → onlyen 二次纯英搜索命中
6. BONUS.DISC / `.extras-1` 目录转移 → 归 `extras/`，不写 transfer_history、不生成 NFO、不发 SubtitleDownload
7. `S01P03` 之类花絮片段编号 → `_episode_re` 放宽命中
8. 站点配 `withinhour=24` → 仅订阅最近 24h 内种子；刷流不受限
9. 过滤规则指定 `orilang=zh` → 中文原始语言命中、英语原始语言被过滤；指定 `other` → 已知列表外语言命中；rule 填了 meta 无 `original_language` → 不阻断
10. 历史/未识别页路径含 `+` 跳转正常编码