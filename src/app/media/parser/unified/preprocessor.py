"""统一预处理 — 合并 anime/prepare.py 与 video/ 预处理逻辑"""

from __future__ import annotations

import re

from app.utils import StringUtils

_META_CHARS = set("粤日英简繁国台港双多单语字幕音轨声频道内嵌封挂压效硬软中外体转载自搬运蓝光高清")

_RE_SITE_TAG = re.compile(
    r"^[【\[]?(?:[动漫画纪录片电影视连续剧集日美韩中港台海外华语综艺原盘高清]{2,}|TV|Animation|Movie|Documentar|Anime|完结][】\]]?|★\d+月新番★)",
    re.IGNORECASE,
)
_RE_FILESIZE = re.compile(r"[0-9.]+\s*[MGT]i?B(?![A-Z]+)", re.IGNORECASE)
_RE_TV_NUMBER = re.compile(r"\[TV\s+(\d{1,4})", re.IGNORECASE)
_RE_4K = re.compile(r"\[4[Kk]]", re.IGNORECASE)
_RE_KANA_TITLE = re.compile(r"[぀-ヿ]+")
# 常见站点/发布站顶级域（用于识别裸域名水印，避开 mkv/mp4 等容器与 web.dl 等元数据）
_SITE_TLDS = (
    r"com|net|org|tv|cc|me|io|to|st|sx|la|ws|xyz|top|club|info|pw"
    r"|co|in|biz|su|ru|eu|se|de|fr|it|pl|es|nl|be|at|ch|pt|cz|ua|ro"
)
# 站点/发布站标记：方括号域名、www 前缀、空白分隔的裸域名
_RE_SITE_MARKER = re.compile(
    rf"\[[\w.-]+\.(?:{_SITE_TLDS})\]"  # [EZTVx.to] / [rarbg.to]
    rf"|\bwww\.[\w-]+(?:\.[A-Za-z]{{2,6}})?"  # www.UIndex.org
    rf"|(?:^|\s)[\w-]+\.(?:{_SITE_TLDS})(?=\s|$)",  # 裸站点域名（空白分隔）
    re.IGNORECASE,
)
_RE_BRACKET_GROUP = re.compile(r"^\[[^\]]+]$")
_RE_AUDIO_BITRATE = re.compile(r"\b\d{2,4}(\.\d+)?\s*(kHz|kbps|bit|bits)\b", re.IGNORECASE)
_RE_AUDIO_FORMAT = re.compile(r"\b(FLAC|ALAC|APE|WAV|AIFF|DSD|DTS|MP3|AAC|OGG|WMA|M4A|Opus)\b", re.IGNORECASE)
_RE_FPS_HZ = re.compile(r"\d+\s*(FPS|HZ)\b", re.IGNORECASE)
# 音轨数标记（如 7.1Audio、5.1AC3、2Audio），X.YAudio 模式容易被 DATE 正则误判为发布日期，需先剥除
_RE_AUDIO_CHANNELS = re.compile(r"\b\d(\.\d)?[-.]?(?:[Aa]udio|[Aa][Cc]-?3|[Aa][Cc]3\b)")
# 日期匹配：负向先行断言，避免误吞 "7.1Audio" 这种音轨数 + Audio 的组合
_RE_DATE = re.compile(r"\d{4}[\s._-]\d{1,2}[\s._-]\d{1,2}(?!\s*[Aa]udio)")
_RE_YEAR_RANGE = re.compile(r"([\s.]+)(\d{4})-(\d{4})")
_RE_LEADING_BRACKET = re.compile(r"^\s*[\[【](.+?)[\]】]")
# 额外内容/花絮后缀（BONUS.DISC、extras-N）：识别标题时剔除，避免混入正式标题/集数
_RE_BONUS_SUFFIX = re.compile(r"[\._ ]BONUS[\._ ]DISC|\.extras-\d+", re.IGNORECASE)
# 合集/系列包装尾巴：CJK 无 \b，必须整段剥，否则「千与千寻的神隐 吉卜力作品合集」会整串去搜 TMDB
_RE_COLLECTION_TAIL = re.compile(
    r"(?:"
    r"[\s._\-]*(?:吉卜力)?作品合集"
    r"|[\s._\-]*系列合集"
    r"|[\s._\-]*电影合集"
    r"|[\s._\-]*剧集合集"
    r"|[\s._\-]*导演合集"
    r"|[\s._\-]*(?:Complete\s+)?Collections?"
    r"|[\s._\-]*全集"
    r"|[\s._\-]*合集"
    r"|[\s._\-]*\d+系列"
    r"|[\s._\-]+系列"
    r")+$",
    re.IGNORECASE,
)
# 「007系列之07金刚钻」这类序号包装，只剥前缀包装词
_RE_SERIES_OF_PREFIX = re.compile(r"^(?:\d{2,3}系列之\d+\s*)")
# 电视台/频道前缀：CCTV4K.Shan.He.Jin.Xiu → Shan.He.Jin.Xiu
_RE_BROADCAST_PREFIX = re.compile(
    r"^(?:CCTV(?:\d+K?|HD|4K)?|CETV\d*|BTV|HBTV|TJTV|SITV|CGTN|NHK|BBC|ITV|CNN|PBS)[\s._-]+",
    re.IGNORECASE,
)
# 站点水印前缀：47BT.人生切割术 → 人生切割术
_RE_SITE_CODE_PREFIX = re.compile(r"^(?:\d{1,3}BT)[\s._-]+", re.IGNORECASE)
# 语言/字幕/制作/类别标记 — 出现在方括号中时应视为标签而非标题
_LANGUAGE_SUBTITLE_RE = re.compile(
    r"[粤粵][语語]|[国國][语語]|日[语語]|繁[体體]|简[体體]|外挂|内嵌|内封|多[语語]|双[语語]"
    r"|[无無]字|生肉|熟肉|中字|繁中|简[中裡]|多国|[国國]漫|日漫|美漫|[动動]漫|[动動]画"
    r"|合成|[压壓]制|配音|二次|字幕|搬[运運]|转载|整理|补档|重发|新番|完结|连载"
    r"|Hi[- ]?Res|USB|Share&PD|无损",
    re.IGNORECASE,
)

# ---- 元数据字段标签 ----
# PT/NFO/豆瓣 的中文描述块形如「东游令 | 导演: 王五 主演: 张三 李四」，
# 标签及其取值属于独立字段，不是片名的一部分。
# （历史 bug：整块被当成片名去搜 TMDB，必然搜不到 → 条目恒为「无法识别媒体信息」）
#
# 安全性来自「词边界」约束：标签前不能紧邻中日韩文字/字母数字，因此
# 《爱的语言》《我们的地区》这类把标签词包在更长词里的片名不会被误伤；
# 更长的「领衔主演」需排在「主演」之前，保证优先匹配更长的标签。
_FIELD_LABEL_WORDS = (
    "领衔主演",
    "主演",
    "导演",
    "編劇",
    "编剧",
    "监制",
    "監製",
    "制片人",
    "製片人",
    "出品",
    "发行",
    "發行",
    "配音",
    "类型",
    "類型",
    "地区",
    "地區",
    "语言",
    "語言",
    "集数",
    "集數",
    "片长",
    "片長",
    "又名",
    "别名",
    "別名",
    "简介",
    "簡介",
    "剧情",
    "劇情",
    "上映日期",
    "首播",
    "评分",
    "評分",
    "标签",
    "標籤",
    "演员表",
    "演員表",
)
_FIELD_LABEL_BOUNDARY = r"(?<![A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff])"
_FIELD_LABEL_RE = re.compile(
    # 冒号形态：`主演: 张三` —— 冒号是强信号，连同冒号一起吃掉
    _FIELD_LABEL_BOUNDARY + r"(?:" + "|".join(_FIELD_LABEL_WORDS) + r")\s*[:：]"
    r"|"
    # 无冒号形态：`主演 张三` —— 要求标签右边也是词边界
    + _FIELD_LABEL_BOUNDARY
    + r"(?:"
    + "|".join(_FIELD_LABEL_WORDS)
    + r")(?=[\s._\-\[\]【】|/]|$)"
)
# 字段取值：标签后紧跟的中文词序列（人名列表），以空格/点号/顿号/斜杠分隔
_FIELD_VALUE_TOKEN_RE = re.compile(
    r"[\s._\-、,，/／|]*(?:[\u4e00-\u9fff\u00b7\u30fb]{1,8})"
)


def strip_collection_noise(text: str) -> str:
    """剥合集/系列包装词，保留作品名。剥空则退回原文，避免误删整名。"""
    if not text:
        return text
    cleaned = _RE_SERIES_OF_PREFIX.sub("", text).strip()
    cleaned = re.sub(r"[\s._\-]*\d+系列", " ", cleaned)
    cleaned = _RE_COLLECTION_TAIL.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-\t")
    return cleaned or text


def is_collection_context(name: str) -> bool:
    """父目录是否为合集/跨季包根。这类目录不能拼进搜索词。"""
    if not name or name in (".", "/", "\\"):
        return True
    return bool(
        re.search(
            r"合集|Collection|全季|系列"
            r"|S\d{1,2}\s*[-~]\s*S\d{1,2}"
            r"|[._\- ]I{1,3}[-~]V?I{0,3}V?\b",
            name,
            re.IGNORECASE,
        )
    )


def strip_field_segments(text: str) -> str:
    """剔除「字段标签 + 取值」片段：`主演: 张三 李四` / `主演.张三.李四` → 空。

    仅在该标签确实作为独立词出现时才处理，避免误伤把标签词包在片名里的情况。
    """
    if not text or not any(word in text for word in _FIELD_LABEL_WORDS):
        return text
    parts: list[str] = []
    pos = 0
    for m in _FIELD_LABEL_RE.finditer(text):
        if m.start() < pos:
            continue
        parts.append(text[pos : m.start()])
        pos = m.end()
        # 吃掉标签后的取值（人名列表）；遇到下一个字段标签即停止
        while True:
            vm = _FIELD_VALUE_TOKEN_RE.match(text, pos)
            if not vm or vm.end() == pos:
                break
            if _FIELD_LABEL_RE.match(vm.group(0).strip(" \t._-、,，/／|")):
                break
            pos = vm.end()
    parts.append(text[pos:])
    return "".join(parts)


def prepare_title(title: str) -> str:
    """统一标题预处理"""
    if not title:
        return title
    title = title.replace("[", "[").replace("]", "]").strip()
    # 剥离站点/发布站标记（[EZTVx.to]、www.UIndex.org、裸域名水印）
    title = _RE_SITE_MARKER.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip()
    # 剥掉水印后遗留的前导分隔符（如 "www.UIndex.org - FBI" → "FBI"）
    title = re.sub(r"^\s*-\s+", "", title)
    title = _RE_FPS_HZ.sub("", title)
    title = _RE_SITE_TAG.sub("", title).strip()
    title = _RE_FILESIZE.sub("", title)
    title = _RE_TV_NUMBER.sub(r"[\1", title)
    title = _RE_4K.sub("2160p", title)
    title = _RE_AUDIO_BITRATE.sub("", title)
    title = _RE_AUDIO_CHANNELS.sub("", title)
    title = _RE_DATE.sub("", title)
    # 合集年份区间保留起始年作为出品年，去掉结束年，避免 2007-2009 被当成 EP 范围
    title = _RE_YEAR_RANGE.sub(r"\1\2", title)
    title = _RE_BROADCAST_PREFIX.sub("", title)
    title = _RE_SITE_CODE_PREFIX.sub("", title)
    # 剔除 BONUS.DISC / .extras-N 花絮后缀，避免被当成正式标题/集数识别
    title = _RE_BONUS_SUFFIX.sub("", title)
    title = strip_collection_noise(title)
    # 剔除元数据字段标签及其取值（主演: 张三 李四 / 导演: 王五），避免描述块混入片名
    title = strip_field_segments(title)
    # 下划线转空格（保留 SAC_2045、x265_10bit 等字母数字间有意义连接，其余拆开）
    title = re.sub(r"(?<![A-Za-z])_|_(?!\d)", " ", title)

    # 移除前缀标签（搬运/合成/粤语等标记性方括号）— 循环移除连续前缀
    for _ in range(3):
        m = _RE_LEADING_BRACKET.match(title)
        if not m:
            break
        inner = m.group(1)
        # 纯数字集数标记 → 保留
        if re.fullmatch(r"\d{1,4}([vV]\d+)?", inner):
            break
        # 语言/字幕/制作标记 → 移除
        if _LANGUAGE_SUBTITLE_RE.search(inner):
            # 方括号内可能是「片名 | 标签」组合（如 [明日方舟 中配 | 国语中字]）：
            # 整块删掉会连片名一起丢；逐段判断，只在确有片名段时保留它们。
            # 保留段要求「含中文且自身不是标签」，因此 [某某字幕组 | 1080p] 这类
            # 纯组名/纯元数据的前导括号仍会整体删除。
            if "|" in inner or "｜" in inner:
                kept = [
                    p.strip()
                    for p in re.split(r"[|｜]", inner)
                    if p.strip() and StringUtils.is_chinese(p) and not _LANGUAGE_SUBTITLE_RE.search(p)
                ]
                if kept:
                    title = re.sub(r"\s+", " ", " ".join(kept) + " " + title[m.end() :]).strip()
                    continue
            title = title[m.end() :]
            continue
        # 发布组标记 → 移除
        has_cjk = bool(re.search(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]", inner))
        looks_like_group = bool(
            re.search(
                r"字幕|压制|制作组|发布组|字幕社|工作室|论坛|奶茶屋|茶屋"
                r"|字幕组|汉化|翻译|搬运|资源组|分享组"
                r"|www\.|\.(?:com|net|cc|org|tv)",
                inner,
                re.IGNORECASE,
            )
        )
        is_short_group_name = (
            not has_cjk and " " not in inner and len(inner) < 30 and re.fullmatch(r"[A-Za-z0-9\-_@.&+³]+", inner)
        )
        # 多组联合发布（A&B）或含字幕组特征词的带空格组名（如 Studio GreenTea&LoliHouse、Nekomoe kissaten）
        is_spaced_group_name = (
            not has_cjk
            and len(inner) < 40
            and re.fullmatch(r"[A-Za-z0-9\-_@.&+³ ]+", inner)
            and ("&" in inner or re.search(r"(?i)fansub|raws|kissaten", inner))
        )
        if looks_like_group or is_short_group_name or is_spaced_group_name:
            title = title[m.end() :]
            continue
        break

    # 处理方括号分隔的多段名称（dmhy/mikan格式）
    # 只有当方括号内不含斜杠、且存在多个方括号时才拆分 — 避免破坏
    # "片名 [中字 | Ardtu]" 这类尾部单个元数据方括号（否则 ] 被吃掉、| 被拆散）
    if "/" not in title and title.count("]") >= 2:
        names = title.split("]")
        if len(names) > 1 and title.find("- ") == -1:
            titles: list[str] = []
            for name in names:
                if not name:
                    continue
                left_char = ""
                if name.startswith("["):
                    left_char = "["
                    name = name[1:]
                if name:
                    if StringUtils.is_chinese(name) and not StringUtils.is_all_chinese(name):
                        if not re.search(r"\[\d+", name, re.IGNORECASE):
                            name = re.sub(r"(?<!\d)[|#:：\-()（）](?!\d)", "", name).strip()
                        if not name or name.strip().isdigit():
                            continue
                        if all(c in _META_CHARS for c in name):
                            continue
                    elif StringUtils.is_all_chinese(name) and all(c in _META_CHARS for c in name):
                        continue
                    if _RE_BRACKET_GROUP.match(name):
                        titles.append(name.strip())
                    else:
                        titles.append(f"{left_char}{name.strip()}")
            return "]".join(titles)
    return title


def extract_japanese_title(title: str) -> str | None:
    """从 dmhy/mikan 格式中提取日文罗马音标题"""
    if not title:
        return None
    parts = re.split(r"[/／]", title)
    for part in parts:
        part = part.strip()
        if _RE_KANA_TITLE.search(part):
            continue
        if re.search(r"[a-zA-Z]{3,}", part) and not re.search(r"[一-鿿]", part):
            return part.strip()
    return None
