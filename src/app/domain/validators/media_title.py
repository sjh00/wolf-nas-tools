"""媒体标题领域校验器 — 过滤无效/垃圾标题，避免无意义的 TMDB 查询."""

import re

# 常见垃圾词黑名单（仅当标题完全由这些词组成时过滤）
_JUNK_WORDS = frozenset(
    [
        "www",
        "com",
        "net",
        "org",
        "tv",
        "download",
        "torrent",
        "magnet",
        "ddl",
        "free",
        "xxx",
        "porn",
        "adult",
        "sex",
        "hentai",
        "r18",
    ]
)

# 成人内容关键词（标题中包含任一即过滤）
_ADULT_PATTERNS = re.compile(
    r"\b(?:"
    r"sex|porn|adult|xxx|hentai|jav|無码|r18|erito|brazzers|realitykings|naughtyamerica|"
    r"bangbros|digitalplayground|teamskeet|mofos|fakehub|blacked|tushy|vixen|danejones|"
    r"bangbus|castingcouch|publicagent|massagerooms|lesbea|momxxx|femaleagent|"
    r"private\.com|privatecasting|legalporno|kink\.com|devianthardcore|"
    r"boundgangbangs|sexandsubmission|hogtied|whippedass|devicebondage|"
    r"obedient|collared|slut|whore|bitch|cumshot|blowjob|anal|threesome|gangbang|"
    r"interracial|milf|stepmom|stepsis|stepbro|stepdad|"
    r"alison tyler|ava addams|lisa ann|riley reid|mia khalifa|kimmy granger|"
    r"lena paul|abella danger|kendra lust|brandi love|jordi|johnny sins"
    r")\b",
    re.IGNORECASE,
)

# 垃圾模式：纯网址类、无意义组合
_GARBAGE_PATTERNS = re.compile(
    r"^(?:www\s+\w+|\w+\s+(?:com|net|org|tv|cc|io)\b(?!\.?\w)|"
    r"\w+\s+\.(?:me)\b|"
    r"(?:pthdtv|qqhdtv|hdtv|hd|4k|1080p|720p)\s*$|"
    r"^\w{1,3}\s+(?:hd|tv|com)$)"
    r"|\b(?:pthdtv|qqhdtv)\b",
    re.IGNORECASE,
)

# 上游（TMDB 社区贡献的译名、PT 种子名）会被灌入推广广告：「站名 + 数字域名」。
# 数字常用 Unicode 数学数字（𝟲/𝟵）与全角数字伪装，站点名与域名之间用全角冒号连接，
# 导致常规"裸域名"规则匹配不到。判定锚点取"纯数字标签域名"——真实片名不会包含
# 4488569.com 这类主机名；同时不把"含 .com"本身当判据，以免误伤《Alibi.com》。
#
# 两条必须同时成立的约束，否则会把正常种子名当广告整段删掉：
# 1. TLD 必须是「终结」的——后面不能再跟 `.`/`-`/字母数字。
#    种子里 `America.1997.CC.BDRip`、`Show.2019.TV.1080p`、`Channel.2021.ME.mkv`
#    的 `.CC`/`.TV`/`.ME` 后面紧跟技术标签，是场景分隔符而不是域名；
#    早期用 `\b` 判定，这些年份+标签会被当成「数字域名广告」删除，
#    直接导致年份丢失、标题被削（如 `电影.2010.CC.BluRay` → `BluRay`）。
# 2. 数字标签不能是 4 位年份（19xx/20xx）——真实广告用长数字 ID（4488569），
#    而 4 位年份在种子命名里几乎总是出品年。
_AD_TLD = r"(?:com|net|org|cc|tv|xyz|top|club|info|pw|me|io)"
_AD_TLD_TERMINAL = r"(?![.\dA-Za-z-])"
_AD_NOT_YEAR = r"(?!(?:19\d{2}|20[0-3]\d)\.)"
_AD_NUMERIC_DOMAIN_RE = re.compile(rf"(?<!\d){_AD_NOT_YEAR}\d{{3,}}\.{_AD_TLD}{_AD_TLD_TERMINAL}", re.IGNORECASE)
_AD_ANY_DOMAIN_RE = re.compile(rf"[\w.-]+\.{_AD_TLD}{_AD_TLD_TERMINAL}", re.IGNORECASE)
_AD_BARE_DOMAIN_RE = re.compile(rf"[\w-]+(?:\.[\w-]+)*\.{_AD_TLD}{_AD_TLD_TERMINAL}", re.IGNORECASE)
_AD_SITE_WORD_RE = re.compile(r"(?:片网|操姦|操奸|黄漫|淫片|色情)")
# 广告片段：站名（可带前后缀中文）+ 数字域名，整体移除
_AD_FRAGMENT_RE = re.compile(
    rf"(?:[一-鿿]{{0,6}}(?:片网|操姦|操奸|黄漫|淫片|色情)[一-鿿]{{0,4}}[\s:：]*)?"
    rf"(?<!\d){_AD_NOT_YEAR}\d{{3,}}\.{_AD_TLD}{_AD_TLD_TERMINAL}",
    re.IGNORECASE,
)


def is_advertisement_title(name: str | None) -> bool:
    """
    判断标题是否被灌入推广广告片段。

    :param name: 待检查的标题
    :return: 是否含广告片段
    """
    if not name:
        return False
    text = str(name)
    if _AD_NUMERIC_DOMAIN_RE.search(text):
        return True
    return bool(_AD_SITE_WORD_RE.search(text) and _AD_ANY_DOMAIN_RE.search(text))


def clean_advertisement_title(name: str | None) -> str | None:
    """
    剥离标题中的推广广告片段。

    未含广告时原样返回；含广告时移除广告片段并返回剩余标题，
    剩余为空返回空串（调用方需回退到其他名称来源）。

    :param name: 待清洗的标题
    :return: 清洗后的标题
    """
    if not name:
        return name
    text = str(name)
    if not is_advertisement_title(text):
        return text
    # 先剥「站名 + 数字域名」粘连成段的情况（如 `某某片网：4488569.com片名`）
    cleaned = _AD_FRAGMENT_RE.sub(" ", text)
    # 再按空白切段，丢弃仍是广告的片段（含数字域名、含站名关键词、或本身就是一个裸域名）
    kept = [
        seg
        for seg in cleaned.split()
        if not (
            _AD_NUMERIC_DOMAIN_RE.search(seg)
            or _AD_SITE_WORD_RE.search(seg)
            or _AD_BARE_DOMAIN_RE.fullmatch(seg.strip("（）()[]【】"))
        )
    ]
    cleaned = re.sub(r"\s{2,}", " ", " ".join(kept))
    return cleaned.strip(" \t:：,，;；-—")


def sanitize_title(name: str | None, fallback: str | None = None) -> str | None:
    """
    清洗标题中的广告片段；清洗后为空时回退到 fallback。

    整条标题都是广告（如「某片网 4488569.com」）时清洗结果为空，
    此时直接置空会让条目失去名称，因此回退到调用方提供的备用名称。

    :param name: 待清洗的标题
    :param fallback: 清洗后为空时使用的备用名称
    :return: 清洗结果或备用名称
    """
    if not name:
        return fallback
    cleaned = clean_advertisement_title(name)
    return cleaned or fallback


def is_valid_media_title(name: str | None) -> bool:
    """
    校验解析后的媒体标题是否有效。

    规则：
    1. 不能为空
    2. 有效字符长度 >= 2
    3. 不能全部是垃圾词
    4. 不能包含成人内容关键词
    5. 不能是网址类垃圾组合

    :param name: 解析出的标题（en_name 或 cn_name）
    :return: 是否有效
    """
    if not name:
        return False
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", name.lower().strip())
    if len(cleaned) < 2:
        return False
    if cleaned in _JUNK_WORDS:
        return False
    if _ADULT_PATTERNS.search(name):
        return False
    if _GARBAGE_PATTERNS.search(name):
        return False
    return True
