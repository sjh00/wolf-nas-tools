import difflib
import re

from app.core.settings import settings
from app.db.repositories.plugin_repo_adapter import MetadataBlacklistRepositoryAdapter
from app.domain.media_types import ProviderMediaType, external_protocol_type
from app.domain.validators.media_title import (
    clean_advertisement_title,
    is_advertisement_title,
    sanitize_title,
)
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.cache_system.metadata_cache import MetadataCache
from app.infrastructure.external.tmdbv3api import (
    TV,
    Discover,
    Episode,
    Find,
    Genre,
    Movie,
    Person,
    Search,
    TMDb,
    Trending,
)
from app.utils import StringUtils
from app.utils.chinese_utils import to_simplified
from app.utils.config_tools import get_tmdbapi_url


class TmdbClient:
    """TMDB API 客户端封装"""

    def __init__(self, metadata_blacklist_repo: MetadataBlacklistRepositoryAdapter | None = None):
        self.tmdb = None
        self.search = None
        self.movie = None
        self.tv = None
        self.episode = None
        self.person = None
        self.find = None
        self.trending = None
        self.discover = None
        self.genre = None
        self._default_language = "zh"
        self._metadata_blacklist_repo = metadata_blacklist_repo or MetadataBlacklistRepositoryAdapter()
        self._init_config()

    def reset(self) -> None:
        """重置配置并清除缓存（热重载时由 ConfigReloader 调用）"""
        self._init_config()
        self.redis_cache.clear_provider("tmdb")
        # API Key 缺失期间 TMDB 查询必然失败并被负缓存，配置修好后必须一并清理。
        MetadataCache(prefix="lookup").clear()

    def _init_config(self):
        # 先清空再按当前配置重建：否则清空/更换 API Key 后仍会沿用旧客户端（表现为"Key 未设置"依旧）
        self.tmdb = None
        self.search = None
        self.movie = None
        self.tv = None
        self.episode = None
        self.person = None
        self.find = None
        self.trending = None
        self.discover = None
        self.genre = None
        app = settings.get("app")
        media = settings.get("media")
        _lang = media.get("tmdb_language", "zh")
        self._default_language = _lang if isinstance(_lang, str) else "zh"
        _api_key = app.get("rmt_tmdbkey")
        if isinstance(_api_key, str) and _api_key:
            self.tmdb = TMDb()
            self.tmdb.domain = get_tmdbapi_url()
            self.tmdb.api_key = _api_key
            self.tmdb.language = self._default_language
            self.search = Search()
            self.movie = Movie()
            self.tv = TV()
            self.episode = Episode()
            self.find = Find()
            self.person = Person()
            self.trending = Trending()
            self.discover = Discover()
            self.genre = Genre()
        self.redis_cache = MetadataCache()
        self.blacklist = self._metadata_blacklist_repo
        self._blacklist_cache = get_cache_manager().get_or_create("metadata_blacklist", "memory", maxsize=1, ttl=300)

    def get_blacklist(self):
        cached = self._blacklist_cache.get("all")
        if cached is not None:
            return cached
        all_items = self.blacklist.get_blacklist()
        self._blacklist_cache.set("all", all_items)
        return all_items

    def set_language(self, language: str = ""):
        if not self.tmdb:
            return
        if language:
            self.tmdb.language = language
        else:
            self.tmdb.language = self._default_language

# ---------- 纯工具函数 ----------

def compare_tmdb_names(file_name, tmdb_names):
    if not file_name or not tmdb_names:
        return False
    if not isinstance(tmdb_names, list):
        tmdb_names = [tmdb_names]
    _fn = StringUtils.handler_special_chars(str(file_name))
    file_name = _fn.upper() if isinstance(_fn, str) else str(file_name).upper()
    file_name_simplified = to_simplified(file_name).upper()
    for tmdb_name in tmdb_names:
        _tn = StringUtils.handler_special_chars(str(tmdb_name))
        tmdb_name = _tn.strip().upper() if isinstance(_tn, str) else str(tmdb_name).strip().upper()
        if file_name == tmdb_name or file_name_simplified == tmdb_name:
            return True
        if len(file_name) < 3 or len(tmdb_name) < 3:
            continue
        is_substring = file_name in tmdb_name or tmdb_name in file_name or file_name_simplified in tmdb_name
        # 中文副标题前缀："太极1" → "太极1从零开始"（冒号已被 handler_special_chars 去掉）。
        # 这类"主标题：副标题"的 ratio 往往低于阈值，需按前缀放行，否则带序号的中文片名搜不到。
        if (
            is_substring
            and len(file_name_simplified) >= 3
            and _has_cjk(file_name_simplified)
            and tmdb_name.startswith(file_name_simplified)
            and len(tmdb_name) - len(file_name_simplified) >= 2
        ):
            return True
        ratio = difflib.SequenceMatcher(None, file_name_simplified, tmdb_name).ratio()
        # 子串匹配阈值放宽：动漫罗马音标题常带 -kun/-chan/-san 等后缀，0.95 过严
        threshold = 0.85 if is_substring else 0.75
        if ratio >= threshold:
            return True
    return False

def _has_cjk(s: str) -> bool:
    """判断字符串是否含 CJK 字符"""
    return bool(re.search(r"[\u3000-\u9fff]", s))


# 跨语言交叉校验的相似度下限。宽松比对用 0.75/0.85，那是同一语言内的容错；
# 这里要区分的是「The Great Long March」与「The Long March」这类不同的作品，
# 相似度约 0.84，必须用更高门槛才能分开。
STRICT_NAME_RATIO = 0.9


def compare_tmdb_names_strict(name, tmdb_names) -> bool:
    """严格名称比对，用于跨语言交叉校验。

    与 compare_tmdb_names 的区别：不做子串放行、不降低阈值。

    真实故障：LLM 把 `The Great Long March` 认成「长征」，中文名搜索命中
    另一部同名老剧《长征》(2001)，其英文名为「The Long March」。用宽松比对
    （子串/0.75）会判定为同一部，于是同一批文件分裂成两个作品。
    严格比对下两者相似度不足 0.9，能被正确拒绝。
    """
    if not name or not tmdb_names:
        return False
    if not isinstance(tmdb_names, list):
        tmdb_names = [tmdb_names]
    _fn = StringUtils.handler_special_chars(str(name))
    target = _fn.upper() if isinstance(_fn, str) else str(name).upper()
    target = target.strip()
    target_simplified = to_simplified(target).upper()
    # 短名保护：拉丁名两三个字母没有区分度（"AB" 会命中一堆），
    # 但中文两字就是完整片名（「长征」），不能一并按长度拒绝。
    min_len = 2 if _has_cjk(target_simplified) else 3
    if len(target) < min_len:
        return False
    for tmdb_name in tmdb_names:
        _tn = StringUtils.handler_special_chars(str(tmdb_name))
        candidate = _tn.strip().upper() if isinstance(_tn, str) else str(tmdb_name).strip().upper()
        if not candidate:
            continue
        if target == candidate or target_simplified == candidate:
            return True
        if len(candidate) < 3:
            continue
        ratio = difflib.SequenceMatcher(None, target_simplified, candidate).ratio()
        if ratio >= STRICT_NAME_RATIO:
            return True
    return False

def get_genre_ids_from_detail(genres):
    if not genres:
        return []
    return [genre.get("id") for genre in genres]

def get_tmdb_chinese_title(tmdbinfo):
    if not tmdbinfo:
        return None
    if external_protocol_type(tmdbinfo.get("media_type")) == ProviderMediaType.MOVIE:
        alternative_titles = tmdbinfo.get("alternative_titles", {}).get("titles", [])
    else:
        alternative_titles = tmdbinfo.get("alternative_titles", {}).get("results", [])
    zh_cn = None
    zh_tw = None
    for alternative_title in alternative_titles:
        iso_3166_1 = alternative_title.get("iso_3166_1")
        title = alternative_title.get("title")
        if not title or not StringUtils.is_chinese(title):
            continue
        # 社区贡献的译名可能被灌入推广广告，含广告的条目直接跳过
        if is_advertisement_title(title):
            continue
        if iso_3166_1 in ("CN", "SG"):
            simplified = to_simplified(title)
            if simplified == title:
                zh_cn = title
                break
        if iso_3166_1 in ("TW", "HK"):
            zh_tw = title
    if not zh_cn and not zh_tw:
        # 中文名常只存在于 translations（zh-CN/zh），alternative_titles 不一定有 CN/TW 条目
        zh_cn, zh_tw = _get_chinese_title_from_translations(tmdbinfo)
    if zh_cn:
        return zh_cn
    if zh_tw:
        return to_simplified(zh_tw)
    if external_protocol_type(tmdbinfo.get("media_type")) == ProviderMediaType.MOVIE:
        return tmdbinfo.get("title")
    return tmdbinfo.get("name")

def _get_chinese_title_from_translations(tmdbinfo):
    """从 translations 提取中文名：优先 zh-CN/zh（简体），回退 zh-TW/zh-HK（繁体）"""
    zh_cn = None
    zh_tw = None
    for tr in (tmdbinfo.get("translations") or {}).get("translations") or []:
        iso = str(tr.get("iso_639_1") or "")
        if not iso.lower().startswith("zh"):
            continue
        data = tr.get("data") or {}
        title = data.get("title") or data.get("name")
        if not title or not StringUtils.is_chinese(title):
            continue
        # 社区贡献的译名可能被灌入推广广告，含广告的条目直接跳过
        if is_advertisement_title(title):
            continue
        if iso.lower() in ("zh-cn", "zh-sg", "zh"):
            simplified = to_simplified(title)
            if simplified == title:
                zh_cn = title
                break
        if iso.lower() in ("zh-tw", "zh-hk", "zh-mo"):
            zh_tw = title
    return zh_cn, zh_tw

def update_tmdbinfo_cn_title(tmdb_info, default_language):
    is_movie = external_protocol_type(tmdb_info.get("media_type")) == ProviderMediaType.MOVIE
    org_title = tmdb_info.get("title") if is_movie else tmdb_info.get("name")
    # ???????zh/zh-CN/zh-Hans...??????????????????
    # ?????????????????????????????????
    needs_cn = not StringUtils.is_chinese(org_title) or is_advertisement_title(org_title)
    if needs_cn and str(default_language or "").lower().startswith("zh"):
        cn_title = get_tmdb_chinese_title(tmdbinfo=tmdb_info)
        if cn_title and cn_title != org_title:
            if is_movie:
                tmdb_info["title"] = cn_title
            else:
                tmdb_info["name"] = cn_title
    # 社区译名可能已被灌入推广广告，兜底剥离后再落库（整条是广告时回退原名）
    if tmdb_info.get("media_type") == ProviderMediaType.MOVIE:
        tmdb_info["title"] = sanitize_title(tmdb_info.get("title"), tmdb_info.get("original_title"))
        tmdb_info["original_title"] = clean_advertisement_title(tmdb_info.get("original_title"))
    else:
        tmdb_info["name"] = sanitize_title(tmdb_info.get("name"), tmdb_info.get("original_name"))
        tmdb_info["original_name"] = clean_advertisement_title(tmdb_info.get("original_name"))
    return tmdb_info
