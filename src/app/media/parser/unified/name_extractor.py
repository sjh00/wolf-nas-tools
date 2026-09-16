"""统一名称提取器 — 五层优先级"""

from __future__ import annotations

import re

from app.media.parser.unified.constants import _ANIME_NO_WORDS, _NAME_NOSTRING_RE, _NAME_YEAR_RE
from app.utils import StringUtils
from app.utils.chinese_utils import to_simplified

from .types import ParseContext

_CHINESE_META_CLEAN = frozenset(
    "粤日英简繁国台港双多单语字幕音轨声频道内嵌封挂压效硬软中外体转载自搬运蓝光高清集话期回首播试预告"
)

# 集标题区域内的元数据词（拒绝将此类词作为集标题）
_EP_TITLE_META_RE = re.compile(
    r"(?i)\b(?:mkv|mp4|avi|ts|m2ts|1080p|2160p|720p|480p|web-?dl|webrip|bluray|bdrip|hdtv|"
    r"h\.?26[45]|x\.?26[45]|hevc|avc|av1|aac|ac3|ddp?\d*\.?\d*|dts|flac|atmos|truehd|hdr\d*|"
    r"dv|sdr|hlg|remux|repack|proper|internal|extended|uncut|theatrical|unrated|rerelease|"
    r"remastered|upscaled|ep\d*|s\d{1,2})\b"
)


def _split_episode_title(ctx: ParseContext) -> str | None:
    """季集号（SxxExx）后的内容切分为集标题，返回季集号之前的主标题剩余文本。

    例: Medalist.S02E09.It.Begins.1080p → 标题 Medalist，集标题 It Begins
    """
    sxx = next((e for e in ctx.elements if e.rule_name == "sxxexx"), None)
    if not sxx:
        return None
    bound = len(ctx.text)
    for e in ctx.elements:
        if e.span[0] >= sxx.span[1] and e.span[0] < bound:
            bound = e.span[0]
    ep_raw = ctx.text[sxx.span[1] : bound]
    ep_title = re.sub(r"\.(?:mkv|mp4|avi|ts|m2ts)$", "", ep_raw, flags=re.IGNORECASE)
    ep_title = re.sub(r"[._\-]+", " ", ep_title).strip()
    if ep_title and not _EP_TITLE_META_RE.search(ep_title):
        ctx.episode_title = ep_title
    return ctx.remaining_text_until(sxx.span[0])


# ---- PT/BT 站点常见元数据 token ----
# 这些 token 出现在英文标题的单词位置时不应被视为片名的一部分
# 格式: 全部小写，使用 (?i) 模式匹配，^...$ 全词匹配
_META_TOKEN_RE = re.compile(
    r"(?i)^("
    # --- 分辨率 ---
    r"\d+p|\d{3,4}x\d{3,4}|[uU]?[hH][dD]|[fF][hH][dD]|[qQ][hH][dD]|[sS][dD]"
    r"|4[Kk]|8[Kk]|uhd|muhd|2160p|1440p|1080[ipIP]|720p|480p|360p"
    # --- 视频编码 ---
    r"|hevc[-\d]*|[hH]\.?265|x\.?265|h265|x265"
    r"|avc|[hH]\.?264|x\.?264|h264|x264"
    r"|(?:hevc|avc|h\.?26[45]|x\.?26[45])[-\d]*bit?"
    r"|av1|vp[89]|mpeg[-]?2|vc[-]?1|wmv[hd]?|xvid|divx|realvideo"
    # --- 音频编码 ---
    r"|aac\d*(\.\d+)?|ac[-]?3|e[-]?ac[-]?3|ddp?\d*(\.\d+)?|dd\+"
    r"|flac\d*(\.\d+)?|alac|ape|wav|wavpack|dsd"
    r"|dts[-.\s]?(hd[-.\s]?ma|hd|x)?\d*([.\s]\d+)?|truehd[-.\s]?\(?atmos\)?|truehd\d*([.\s]\d+)?|\(?atmos\)?"
    r"|mp3\d*|mp2|opus|ogg|vorbis|wma"
    r"|lpcm\d*(\.\d+)?|pcm|dolby[-\s]?digital"
    # --- HDR/色彩 ---
    r"|hdr\d*|hdr10\+?|dovi|dv|sdr|10[-]?bit|8[-]?bit|hi10p"
    # --- 来源/平台 ---
    r"|web[-]?(dl|rip|dlr|dlmux|dlrip)?|webcast|webtv"
    r"|blu[-]?ray|bluray|bd(rip|mv|remux|iso|25|50|66|100)?|bd[-]?rip|bdmv"
    r"|uhd[-]?bluray|4k[-]?uhd"
    r"|remux|bdremux|hddvd|hd[-]?dvd"
    r"|dvd(rip|r|screener|scr|5|9)?|dvd[-]?rip|dvd[-]?r|dvdscr"
    r"|hdtv|uhdtv|pdtv|dsr|dsrip|tvrip|stv"
    r"|hd[-]?tc|tc|telesync|telecine|cam|camera|r5|r6|screener|scr"
    # 注意：不把单独 "max" 当元数据——"Mad Max" 的 Max 是片名；HBO Max 用 hmax/hbomax 标记
    r"|amzn|amazon|nf|netflix|hulu|dsnp|disney|atvp|apple|hmax|hbomax|itunes"
    r"|pcok|peacock|pmtp|paramount|shdr|showtime|appletv|vudu|fandango"
    r"|mubi|criterion|shoutfactory|arrow|radiance|capelight|kino|cocp|eureka|bfi"
    r"|baha|cr|crunchyroll|abema|ani-one|ani|b-global|bilibili|viutv|myvideo"
    r"|friday|kktv|linetv|catchplay|iqiyi|youku|tencent|mgtv|wetv|galaxy|gimy"
    # --- 地区代码 ---
    r"|eur|gbr|ger|kor|jpn|usa|fra|ita|esp|deu|aus|can|chn|hkg|twn|sgp|ind|tha|nld|bel|dnk|swe|nor|fin|prt|bra|mex|arg"
    # --- 发布组 ---
    r"|rarbg|yts|yify|eztv|ettv|etrg|gtm|fgt|cmrg|evo|ntg|pse|tgx|galaxyrg|hive|ctrlhd"
    r"|audies|adweb|nest|runrun|dramas|fhdx|xpost|tigole|joybell|utr|qman|psa|rmteam"
    r"|mteam|beitai|ourbits|hdsky|hdc|chd|ttg|pter|keepfrds|frds|hds|hdfans"
    # --- 版本/内容标签 ---
    r"|diy|repack|proper|rerip|internal|int"
    r"|limited|extended|uncut|unrated|directors?[-]?cut|dc"
    r"|theatrical|remastered|anniversary|special[-]?edition"
    r"|imax|open[-]?matte|widescreen|letterbox"
    r"|uncensored|censored|decensored"
    # --- 音轨/字幕 ---
    r"|dual[-]?audio|multi[-]?audio|multi[-]?subs?|dual|multi"
    r"|\d(\.\d)?[-]?audio"
    r"|dub(bed)?|sub(bed)?|hard[-]?sub|soft[-]?sub|eng[-]?sub"
    r"|ch[st]|chs|cht|jpsc|jptc|jps|jpt|srt|srtx?\d*|assx?\d*|ssax?\d*|idx|sup|pgs"
    r"|gb|big5"
    # --- 剧集标记 ---
    # 注意：不把单独 "season" 当元数据——"The Long Season"/"Cherry Season" 的 Season 是片名。
    # 季节识别交给 season_keyword 规则（Season 1/2）；batch/collection/pack 等仍按元数据剥离
    r"|complete|batch|collection|pack|trilogy|quadrilogy"
    r"|mini[-]?series|mini|ova\d*|special|ova|ond[ae]s?|sp\d*"
    r"|ep(isode)?\d*|part\d+|chapter\d*|vol(ume)?\d*"
    # --- 频道 ---
    r"|bbc|itv|channel\s*[45]|cnn|fox|abc|nbc|cbs|hbo|starz|showtime|amc|tnt|tbs|fx|syfy"
    r"|cctv\d*k?|cgtn|nhk"
    # --- 附加片段 ---
    r"|plus|extra|bonus|deleted|featurette|behind[-]?the[-]?scenes|making[-]?of|gag[-]?reel|trailer|teaser"
    r"|shot|interview|preview|sneak[-]?peek|recap|highlights"
    # --- 容器 ---
    r"|mp4|mkv|avi|ts|m2ts|mov|wmv|flv|rmvb|iso|img"
    # --- 其他 ---
    r"|x\.?\d{2,4}|h\.?\d{2,4}|h26[345]|rev\d*|v\d"
    r"|jav|fhd|hq|fixed|nuked|proper"
    r"|nvenc|qsv|amf|vce|x26[45]"
    r"|s\d{2,4}"
    # --- 类型/杂项标签 ---
    r"|share|pd|disc|hi[-]?res|usb"
    r"|se\d{1,2}"
    r"|@\w+"
    r"|[0-9a-fA-F]{8}"
    r"|\d+[-]?bit"
    r"|movie([+&]?\w+)?|tv[+&]?\w*"
    r")$"
)

_GROUP_KEYWORDS_RE = re.compile(
    r"字幕|压制|制作组|发布组|字幕社|工作室|论坛|奶茶屋|茶屋|字幕组|汉化|翻译|搬运|资源组|分享组",
    re.IGNORECASE,
)
# 版本短语：整体剔除（如 Extended Version / Theatrical Cut / Director's Edition）
_VER_PHRASE_RE = re.compile(
    r"(?i)\b(?:extended|uncut|unrated|theatrical|remastered|anniversary|special|"
    r"director'?s?|final|ultimate|complete|original|international)\s+(?:version|cut|edition)\b"
)

# 全大写"编码组-发布组"链（如 MNHD-FRDS），整段视为发布组而非片名
_RE_GROUP_CHAIN = re.compile(r"^[A-Z0-9]{2,8}(?:-[A-Z0-9]{2,8})+$")

# 尾部特集描述词：仅在标题主体之后出现时视为元数据（Pilot 单独成片名时保留）
_SPECIAL_DESC_WORDS = frozenset({"pilot", "premiere", "prologue", "special"})

_RE_KANA_TITLE = re.compile(r"[぀-ヿ]+")

# 剧集说明/预告类词：出现在标题里是元数据，不是片名（试播集/首播/预告/第X集等）
_EP_META_WORDS_RE = re.compile(
    r"(?i)^(?:"
    r"试播集?|首播|先行(?:版|放送)?|预告(?:片|篇)?|特典|片头(?:曲)?|片尾(?:曲)?|"
    r"第\s*[0-9一二三四五六七八九十百零]+\s*[集话期回]|[0-9]+\s*[集话期回]|"
    r"本篇|总集篇|特番|特别篇|剧场版预告|pv|cm|sp|ova\d*|oad\d*"
    r")$"
)


def extract_name(ctx: ParseContext, original_text: str) -> None:
    """从剩余文本中提取名称，填充 ctx 的 cn_name / en_name / jp_title"""
    remaining = ctx.remaining_text()
    if not remaining.strip():
        return

    # 清理剩余文本中的元数据方括号
    remaining = _clean_metadata_brackets(remaining)
    if not remaining.strip():
        return

    # 切分季集号后的集标题（Medalist.S02E09.It.Begins → 标题 Medalist + 集标题 It Begins）
    if not ctx.episode_title:
        _title_remaining = _split_episode_title(ctx)
        if _title_remaining:
            remaining = _title_remaining

    # 剩余文本中的点号为文件名分隔符 → 转空格以便名称提取
    remaining = remaining.replace(".", " ")

    # 从原始标题中提取被预处理移除的发布组（在所有 name layer 前执行）
    _extract_group_from_original(ctx, ctx.text, original_text)

    # Layer 2: 斜杠分隔格式
    if "/" in remaining:
        _extract_slash_name(ctx, remaining)
        if ctx.cn_name or ctx.en_name:
            return

    # Layer 3: 方括号内容分析（使用预处理后的文本，避免重复识别已移除的发布组）
    _extract_bracket_name(ctx, ctx.text, original_text)
    if ctx.cn_name and ctx.en_name:
        return

    # Layer 4: 自由文本分析
    _extract_free_text(ctx, remaining)
    if ctx.cn_name or ctx.en_name:
        return

    # Layer 5: 降级恢复 — 从原始标题恢复
    _recover_from_original(ctx, original_text)


def _clean_metadata_brackets(text: str) -> str:
    """移除方括号中的元数据内容（保留非元数据内容）"""

    def replace_bracket(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner:
            return ""
        if _is_metadata(inner) or _GROUP_KEYWORDS_RE.search(inner):
            return ""
        if re.fullmatch(r"[\s\-_\.]*", inner):
            return ""
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", replace_bracket, text)


def _is_chinese_title(text: str) -> bool:
    """判断文本是否为中文标题（含全角标点）"""
    if not text:
        return False
    cleaned = re.sub(r"[！？：；，。、（）《》〈〉【】「」『』～·]", "", text)
    return StringUtils.is_all_chinese(cleaned) if cleaned else False


def _extract_slash_name(ctx: ParseContext, text: str) -> None:
    """处理 '中文 / English / 日文' 格式"""
    bracket_contents = re.findall(r"\[([^\]]+)\]", ctx.text)
    for bc in bracket_contents:
        if "/" not in bc:
            continue
        parts = [p.strip() for p in bc.split("/") if p.strip()]
        if len(parts) < 2:
            continue
        if _is_metadata(parts[0]) or _is_metadata(parts[-1]):
            continue
        cn_parts = [p for p in parts if _is_chinese_title(p)]
        en_parts = [p for p in parts if not StringUtils.is_chinese(p) and not _RE_KANA_TITLE.search(p)]
        if cn_parts:
            cn = re.sub(r"\s*\([^)]*\)\s*", " ", cn_parts[0]).strip()
            cn = re.sub(r"\s*第\s*\d+\s*季\s*$", "", cn).strip()
            ctx.cn_name = cn
        if en_parts:
            ctx.en_name = en_parts[-1]
        if ctx.cn_name or ctx.en_name:
            return

    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) < 2:
        return
    left = _clean_cn_part(parts[0])
    right = parts[-1]
    if StringUtils.is_chinese(left) and not _is_chinese_title(right):
        ctx.cn_name = left
        ctx.en_name = right
    elif _is_chinese_title(right) and not StringUtils.is_chinese(left):
        ctx.en_name = left
        ctx.cn_name = _clean_cn_part(right)
    elif not StringUtils.is_chinese(right) or len(parts) > 1:
        ctx.en_name = right if not _is_chinese_title(right) else left


def _clean_cn_part(text: str) -> str:
    """清理中文名称段：移除括号别名、季数标记、尾部集数"""
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    text = re.sub(r"\s*第\s*\d+\s*季\s*$", "", text).strip()
    text = re.sub(r"\s+-\s*\d+\s*$", "", text).strip()
    return text


def _extract_group_from_original(ctx: ParseContext, prepared_text: str, original_text: str) -> None:
    """从原始标题中提取被预处理移除的发布组括号（在所有 name 提取层之前执行）"""
    if ctx.release_group or original_text == prepared_text:
        return
    for m in re.finditer(r"\[([^\]]+)\]", original_text):
        inner = m.group(1).strip()
        if _GROUP_KEYWORDS_RE.search(inner) and not all(c in _CHINESE_META_CLEAN for c in inner):
            ctx.release_group = inner
            break


def _extract_bracket_name(ctx: ParseContext, prepared_text: str, original_text: str) -> None:
    """从方括号内容中提取名称（含 bracket 前的文本）"""
    release_group = str(ctx.release_group or "").strip()

    for m in re.finditer(r"\[([^\]]+)\]", prepared_text):
        bc_clean = m.group(1).strip().replace("_", " ").strip()
        if not bc_clean or len(bc_clean) < 2:
            continue
        if _is_metadata(bc_clean):
            continue
        if re.fullmatch(r"\d{1,3}", bc_clean):
            # 纯数字括号是集号/文件号标记（如 [13]、[01]），不是标题
            continue
        if release_group and bc_clean.upper() == release_group.upper():
            continue
        if _GROUP_KEYWORDS_RE.search(bc_clean):
            if not ctx.release_group:
                ctx.release_group = bc_clean
            continue

        # PT 描述块（`片名 | 国语中字 | 1080p`）：竖线分段后只保留非元数据段，
        # 否则整块会被当作片名（历史 bug：`[东游令 | 国语中字 | 1080p]` 片名带上元数据）
        if "|" in bc_clean or "｜" in bc_clean:
            kept = [p.strip() for p in re.split(r"[|｜]", bc_clean) if p.strip() and not _is_metadata(p.strip())]
            if not kept:
                continue
            bc_clean = " ".join(kept)

        # 提取 bracket 前的文本作为潜在中文名
        prefix = prepared_text[: m.start()].strip()
        cn_in_prefix = _extract_cn_from_prefix(prefix)
        if cn_in_prefix and not ctx.cn_name:
            ctx.cn_name = cn_in_prefix

        if StringUtils.is_chinese(bc_clean):
            # 中英混合方括号（如 [Person of Interest (试播集)] / [攻壳机动队ARISE Alternative Architecture]）：
            # 拆出中文与英文；中文全是元数据词时丢弃中文只留英文，否则中文作 cn_name、英文作 en_name
            if re.search(r"[A-Za-z]{2,}", bc_clean):
                cn_words = [w for w in re.findall(r"[\u4e00-\u9fff]+", bc_clean) if not _is_metadata(w)]
                en_words = re.findall(r"[A-Za-z][A-Za-z0-9]*", bc_clean)
                if not cn_words:
                    # 中文全是元数据（如"试播集"）→ 英文作 en_name
                    if en_words and not ctx.en_name:
                        ctx.en_name = " ".join(en_words)
                    return
                ctx.cn_name = ctx.cn_name or "".join(cn_words)
                if en_words and not ctx.en_name:
                    ctx.en_name = " ".join(en_words)
                return
            ctx.cn_name = ctx.cn_name or bc_clean
        else:
            # 无空格的纯字母数字方括号是发布组/字幕组（如 [Ardtu]），
            # 不是英文片名；英文片名通常含空格或多个词
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9@._-]*", bc_clean) and " " not in bc_clean:
                if not ctx.release_group:
                    ctx.release_group = bc_clean
                if ctx.cn_name:
                    return
                continue
            ctx.en_name = ctx.en_name or bc_clean
        if ctx.cn_name or ctx.en_name:
            return

    # fallback: 搜索中文名候选
    if not ctx.cn_name:
        bracket_contents = re.findall(r"\[([^\]]+)\]", prepared_text)
        for bc in bracket_contents:
            bc_clean = bc.strip().replace("_", " ").strip()
            if release_group and bc_clean.upper() == release_group.upper():
                continue
            if _GROUP_KEYWORDS_RE.search(bc_clean):
                continue
            if _is_metadata(bc_clean):
                continue
            # 标签类方括号（新番/连载/国漫/国语中字/类型 等）不是片名
            if re.search(r"新番|连载|国漫|国语|中字|类型[：:]|年番|双语", bc_clean):
                continue
            if StringUtils.is_chinese(bc_clean) and len(bc_clean) >= 4:
                if all(c in _CHINESE_META_CLEAN for c in bc_clean):
                    continue
                ctx.cn_name = bc_clean
                break


def _extract_cn_from_prefix(text: str) -> str | None:
    """从 bracket 前的文本中提取中文名（处理 攻殻機動隊[Ghost 格式）"""
    if not text:
        return None
    # 取最后一个中文片段
    cn_match = re.search(r"[\u4e00-\u9fff\u3000-\u303F\uFF00-\uFFEF]+$", text)
    if cn_match:
        word = cn_match.group(0).strip()
        if _is_metadata(word):
            return None
        return word
    return None


def _extract_free_text(ctx: ParseContext, text: str) -> None:
    """从自由文本中提取名称"""
    # 中西文边界补空格：避免"瑞克和莫蒂Rick and Morty"被当成一个混合词，
    # 导致中文名混入英文字母、英文名被截断
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z])|(?<=[A-Za-z])(?=[\u4e00-\u9fff])", " ", text)
    text = text.replace("|", " ").replace("｜", " ")
    text = re.sub(r"\[[^\]]*\]", "", text).strip()
    text = re.sub(r"「[^」]*」", " ", text).strip()  # 日文括号→空格防粘连
    text = re.sub(r"\[\s*\]", "", text).strip()
    text = re.sub(r"[\[\]]", "", text).strip()  # 残留单边括号
    text = re.sub(r"\([^)]*\)", "", text).strip()
    text = re.sub(r"（[^）]*）", "", text).strip()  # 全角括号（如 （试播集））
    text = re.sub(r"\s*第\s*\d+\s*季\s*$", "", text)
    text = re.sub(r"\s+S\d{1,2}\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+-\s*\d+\s*$", "", text)
    text = re.sub(r"-[^-]{1,10}-(?=\s|$)", "", text).strip()

    # ~...~ 为日文副标题标记 → 提取为 episode_title，不参与名称
    sub_match = re.search(r"~([^~]+)~", text)
    if sub_match:
        ctx.episode_title = sub_match.group(1).strip() or ctx.episode_title
        text = text.replace(sub_match.group(0), " ").strip()

    # 【...】CJK 全角方括号标签（生/附日字/字幕/内嵌等）→ 元数据，移除
    text = re.sub(r"【[^】]*(?:生|附日字|字幕|熟肉|生肉|内嵌|内封|外挂|日字|简繁|多语|双语)[^】]*】", " ", text).strip()

    # 提取发布组后缀 (空格-Name 格式)，支持多词组名（如 "-Mo Cuishle"）。
    # 要求每个词首字母大写且不含高频标题词，避免误伤 "Movie Title - The Beginning"
    for team_match in re.finditer(r"\s-\s*([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,2})\s*$", text):
        cand = team_match.group(1)
        if any(w.lower() in _HIGH_FREQ_TITLE_WORDS for w in cand.split()):
            continue
        ctx.release_group = cand
        text = text[: team_match.start()].strip()
        break

    # 版本短语整体剔除（Extended Version / Theatrical Cut 等）
    text = _VER_PHRASE_RE.sub(" ", text).strip()

    # 替换非数字间的点为分隔符（含数字后的末尾点如 2045.）
    text = re.sub(r"(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 剥离附加集标记（+SPx1、SP01、+OVA、OAD01 等）
    text = re.sub(r"\+?\s*(?:SP|OVA|OAD)\s*x?\s*\d+", "", text, flags=re.IGNORECASE).strip()

    # 移除十进制版本号
    text = re.sub(r"\b\d+\.\d+\b", "", text).strip()
    # 集数总量说明（Ep03 of 6）不是片名
    text = re.sub(r"\bof\s+\d+\b", " ", text, flags=re.IGNORECASE).strip()

    # 清理尾部方括号（追踪器标签如 [rartv]、[ettv] 等）
    text = re.sub(r"(?i)\[[a-z0-9]+\]\s*$", "", text).strip()

    # 清理尾部容器格式（.mkv .mp4 等），避免阻塞发布组提取
    text = re.sub(r"(?i)\b(mkv|mp4|avi|ts|m2ts|mov|wmv|flv|rmvb|iso|img)\s*$", "", text).strip()

    # 提取发布组后缀 (-DIy@Group / -GROUP / -Group@Site 格式)
    group_match = re.search(r"-([A-Za-z][A-Za-z0-9]*(?:@\w+)?)\s*$", text)
    if group_match:
        ctx.release_group = group_match.group(1)
        text = text[: group_match.start()].strip()
        # 形如 "MNHD-FRDS" 的"编码组-发布组"链：紧邻的全大写组名一并剥离
        chain_prev = re.search(r"[-.\s]+([A-Z0-9]{2,8})$", text)
        if chain_prev and any(c.isalpha() for c in chain_prev.group(1)):
            text = text[: chain_prev.start()].strip()

    # 通用后缀剥词：剥离尾部短词（语种缩写、质量标签等）
    while True:
        m = re.search(r"([A-Za-z0-9_]+)[!?。，,;；：:\s]*$", text)
        if not m or _is_likely_title_word(m.group(1)):
            break
        stripped = text[: m.start()].strip()
        if not stripped:
            break
        # 只剩 1-2 个词时视为标题，不再剥离
        if len(stripped.split()) <= 2:
            break
        # Part/Vol 后的数字是片名（A Chinese Odyssey Part 1）
        prev_word = stripped.split()[-1].lower()
        if m.group(1).isdigit() and prev_word in {"part", "vol", "volume", "chapter", "pt"}:
            break
        text = stripped

    # 再次清理残留的点号与尾部连字符/分隔符
    text = re.sub(r"(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)", " ", text)
    text = re.sub(r"[\s\-|]+\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text or text in _ANIME_NO_WORDS:
        return
    # 纯数字短片名（65 / 24 / 2012）不能因长度 < 3 被丢掉
    if len(text) < 3 and not StringUtils.is_chinese(text) and not text.isdigit():
        return

    words = text.split()
    if not words:
        return

    cn_parts: list[str] = []
    en_parts: list[str] = []
    for idx, word in enumerate(words):
        word = word.removesuffix("]")
        if not word:
            continue
        if _META_TOKEN_RE.match(word):
            continue
        # 仅丢掉编码碎片（H.264 拆出的 H/X），不要误伤 He/E 这类片名词
        if len(word) == 1 and word.lower() in ("h", "x"):
            continue
        # 全大写"编码组-发布组"链（MNHD-FRDS）：整段视为发布组
        if _RE_GROUP_CHAIN.match(word):
            if not ctx.release_group:
                ctx.release_group = word.rsplit("-", 1)[-1]
            continue
        # 尾部特集描述词（Pilot/Premiere 等）：标题主体之后出现才算元数据
        if idx > 0 and word.lower() in _SPECIAL_DESC_WORDS:
            continue
        if word.isdigit():
            # 纯数字词：位于名称中部时，后面还有非元数据字母词才视为标题本体数字
            # （The 100 Girlfriends）；末尾孤立数字视为解析残留丢弃（7.1 声道被拆成 "7 1"）。
            # 位于名称起始处的多位数字是片名本体（24 / 1917），需保留
            # 片名中的年份（Wonder Woman 1984）不是出品年时也保留
            followed_by_title_word = any(
                w[:1].isalpha() and not _META_TOKEN_RE.match(w) for w in words[idx + 1 :]
            )
            is_title_year = (
                len(word) == 4
                and 1900 <= int(word) <= 2030
                and word != str(ctx.year or "")
            )
            prev = words[idx - 1].lower() if idx > 0 else ""
            after_part_word = prev in {"part", "vol", "volume", "chapter", "pt"}
            if (
                followed_by_title_word
                or is_title_year
                or after_part_word
                or (idx == 0 and len(word) >= 2 and not cn_parts and not en_parts)
            ):
                en_parts.append(word)
            continue
        # 处理"数字 + 元数据中文词"组合，如 "7声轨"、"3音轨"、"5声道"
        digit_prefix = re.match(r"^\d+(?:\.\d+)?", word)
        if digit_prefix and digit_prefix.end() < len(word):
            rest = word[digit_prefix.end() :]
            if rest and _is_metadata(rest):
                continue
        if StringUtils.is_chinese(word):
            # 过滤纯元数据的汉字词（如 日语中字、新番、连载等）
            if _is_metadata(word):
                continue
            cn_parts.append(word)
        else:
            en_parts.append(word)

    # 仅填充缺失的名称，避免覆盖方括号层已提取的更可靠 cn/en 名
    if cn_parts and not ctx.cn_name:
        ctx.cn_name = " ".join(_dedup_adjacent(cn_parts))
    if en_parts and not ctx.en_name:
        ctx.en_name = " ".join(_dedup_adjacent(en_parts))


def _looks_like_group_token(text: str) -> bool:
    """判断是否为发布组/字幕组 token（无空格的纯字母数字，如 Ardtu、FRDS）"""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9@._-]*", text)) and " " not in text


def _dedup_adjacent(words: list[str]) -> list[str]:
    """去除相邻重复词（我们这一天 我们这一天 → 我们这一天）"""
    result: list[str] = []
    for w in words:
        if not result or w != result[-1]:
            result.append(w)
    return result


def _recover_from_original(ctx: ParseContext, original_text: str) -> None:
    """从原始标题恢复名称"""
    if "/" in original_text:
        for part in original_text.split("/"):
            part = part.strip()
            if StringUtils.is_all_chinese(part) and len(part) >= 2:
                ctx.cn_name = part
                break

    if not ctx.jp_title:
        parts = re.split(r"[/／]", original_text)
        for part in parts:
            part = part.strip()
            if _RE_KANA_TITLE.search(part):
                continue
            if re.search(r"[a-zA-Z]{3,}", part) and not re.search(r"[一-鿿]", part):
                ctx.jp_title = part.strip()
                break


_HIGH_FREQ_TITLE_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "our",
        "you",
        "are",
        "not",
        "but",
        "all",
        "one",
        "of",
        "in",
        "to",
        "is",
        "it",
        "on",
        "at",
        "we",
        "no",
        "so",
        "be",
        "me",
        "my",
        "mr",
        "mrs",
        "ms",
        "dr",
        "st",
        "vs",
        "or",
    }
)


def _is_likely_title_word(word: str) -> bool:
    """常见标题词汇（非发布组）"""
    return word.lower() in _HIGH_FREQ_TITLE_WORDS or len(word) > 2


def _is_metadata(text: str) -> bool:
    """检测文本是否为元数据（非名称）"""
    if _META_TOKEN_RE.match(text):
        return True
    if _EP_META_WORDS_RE.match(text.strip()):
        return True
    if all(c in _CHINESE_META_CLEAN for c in text):
        return True
    # "中字 | Ardtu" / "简繁 | 1080p" 这类竖线分隔组合：各段都是元数据/发布组则整体视为元数据
    if "|" in text or "｜" in text:
        parts = [p.strip() for p in re.split(r"[|｜]", text) if p.strip()]
        if parts and all(_is_metadata(p) or _looks_like_group_token(p) for p in parts):
            return True
    # 点分隔的多词元数据（如 WEB.1080p.AV1）
    dot_tokens = text.replace(".", " ").split()
    if len(dot_tokens) >= 2 and all(_META_TOKEN_RE.match(tk) for tk in dot_tokens):
        return True
    tokens = text.split()
    if len(tokens) >= 2 and all(_META_TOKEN_RE.match(tk) for tk in tokens):
        return True
    if len(tokens) >= 2 and all(all(c in _CHINESE_META_CLEAN for c in tk) for tk in tokens):
        return True
    if len(tokens) >= 2 and any(_META_TOKEN_RE.match(tk) for tk in tokens):
        non_meta = [tk for tk in tokens if not _META_TOKEN_RE.match(tk)]
        if all(all(c in _CHINESE_META_CLEAN for c in tk) for tk in non_meta):
            return True
    return False


def _strip_name_noise(name: str, release_year: str | None = None) -> str:
    """剥离季集标记与合集词。

    年份：仅剥掉与出品年相同的尾巴（Movie 2020 → Movie），片名中的年份保留
    （Wonder Woman 1984）。若剥离后为空则保留原名（片名即年份，如 2012）。
    """
    stripped = re.sub(rf"{_NAME_NOSTRING_RE}", "", name, flags=re.IGNORECASE).strip()
    stripped = re.sub(r"\b(C(?:omplete|OMPLETE)|全集|合集|Season\s+\d+)\b", "", stripped, flags=re.IGNORECASE).strip()
    if release_year and re.search(rf"\b{re.escape(release_year)}\b", stripped):
        candidate = re.sub(rf"[\s._-]*{re.escape(release_year)}\s*$", "", stripped).strip()
        if candidate:
            stripped = candidate
    if stripped:
        return stripped
    if re.fullmatch(_NAME_YEAR_RE, name.strip()):
        return name.strip()
    return stripped


def clean_names(ctx: ParseContext) -> None:
    """清理并标准化提取到的名称"""
    if ctx.cn_name:
        # 收口：清残留分隔符/单边括号，去除相邻重复词
        ctx.cn_name = re.sub(r"[\s\|\/\[\]\(\)（）【】「」『』＜＞]+", " ", ctx.cn_name).strip()
        ctx.cn_name = " ".join(_dedup_adjacent(ctx.cn_name.split()))
        _, ctx.cn_name, _, _, _, _ = StringUtils.get_keyword_from_string(ctx.cn_name)
        if ctx.cn_name:
            ctx.cn_name = _strip_name_noise(ctx.cn_name, ctx.year)
            if ctx.cn_name:
                ctx.cn_name = to_simplified(ctx.cn_name)
    if ctx.en_name:
        ctx.en_name = re.sub(r"[\s\|\/\[\]\(\)（）【】「」『』＜＞]+", " ", ctx.en_name).strip()
        ctx.en_name = " ".join(_dedup_adjacent(ctx.en_name.split()))
        ctx.en_name = _strip_name_noise(ctx.en_name, ctx.year)
        if ctx.en_name:
            ctx.en_name = ctx.en_name.title()
