"""
PathUtils - 路径相关纯函数工具
从 Config 类拆分出来，避免循环导入
"""

import os
import re

from app.core.constants import RMT_MIN_FILESIZE
from app.core.root_path import get_project_root
from app.core.settings import settings

# 下载器未完成临时文件后缀（迅雷 .xltd，qBittorrent/Aria2 等）
INCOMPLETE_DOWNLOAD_SUFFIXES = (".xltd", ".part", ".!qb", ".aria2")
_INCOMPLETE_SCAN_DEPTH = 2


def get_config_path():
    """配置目录路径"""
    return settings.config_path


def get_data_path():
    """运行时数据目录路径"""
    return settings.data_path


def get_root_path():
    """项目根目录"""
    return str(get_project_root())


def get_temp_path():
    """临时文件目录"""
    return os.path.join(get_data_path(), "temp")


def get_inner_config_path():
    """内置配置模板目录"""
    return os.path.join(get_root_path(), "config")


def get_user_plugin_path():
    """用户插件目录"""
    return os.path.join(get_data_path(), "plugins")


class PathUtils:
    @staticmethod
    def join_path(base: str, *parts: str) -> str:
        """按 base 的路径风格拼接，避免 Windows 给 POSIX 路径插入反斜杠。

        媒体库/远端后端路径统一是 POSIX 风格，直接 os.path.join 在 Windows 上
        会产出 `/media/tv\\Show` 这类混合分隔符，导致比对与落库记录不一致。
        """
        text = str(base or "")
        if not text:
            return ""
        sep = "\\" if (re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\")) else "/"
        result = text
        for part in parts:
            piece = str(part or "")
            if not piece:
                continue
            if not result.endswith(("/", "\\")):
                result += sep
            result += piece.lstrip("/\\")
        return result

    @staticmethod
    def get_dir_files(in_path, exts: str | list = "", filesize=0, episode_format=None):
        """
        获得目录下的媒体文件列表List ，按后缀、大小、格式过滤
        """
        if not in_path:
            return []
        if not os.path.exists(in_path):
            return []
        ret_list = []
        if os.path.isdir(in_path):
            for root, _dirs, files in os.walk(in_path):
                for file in files:
                    cur_path = os.path.join(root, file)
                    # 检查路径是否合法
                    if PathUtils.is_invalid_path(cur_path):
                        continue
                    # 检查格式匹配
                    if episode_format and not episode_format.match(file):
                        continue
                    # 检查后缀
                    if exts and os.path.splitext(file)[-1].lower() not in exts:
                        continue
                    # 检查文件大小
                    if filesize and os.path.getsize(cur_path) < filesize:
                        continue
                    # 命中（os.walk 不会重复，无需去重检查）
                    ret_list.append(cur_path)
        else:
            # 检查路径是否合法
            if PathUtils.is_invalid_path(in_path):
                return []
            # 检查后缀
            if exts and os.path.splitext(in_path)[-1].lower() not in exts:
                return []
            # 检查格式
            if episode_format and not episode_format.match(os.path.basename(in_path)):
                return []
            # 检查文件大小
            if filesize and os.path.getsize(in_path) < filesize:
                return []
            ret_list.append(in_path)
        return ret_list

    @staticmethod
    def get_dir_level1_files(in_path, exts: str | list = ""):
        """
        查询目录下的文件（只查询一级）
        """
        ret_list = []
        if not os.path.exists(in_path):
            return []
        for file in os.listdir(in_path):
            path = os.path.join(in_path, file)
            if os.path.isfile(path):
                if not exts or os.path.splitext(file)[-1].lower() in exts:
                    ret_list.append(path)
        return ret_list

    @staticmethod
    def get_dir_level1_medias(in_path, exts: str | list = ""):
        """
        根据后缀，返回目录下所有的文件及文件夹列表（只查询一级）
        """
        ret_list = []
        if not os.path.exists(in_path):
            return []
        if os.path.isdir(in_path):
            for file in os.listdir(in_path):
                path = os.path.join(in_path, file)
                if os.path.isfile(path):
                    if not exts or os.path.splitext(file)[-1].lower() in exts:
                        ret_list.append(path)
                else:
                    ret_list.append(path)
        else:
            ret_list.append(in_path)
        return ret_list

    @staticmethod
    def is_invalid_path(path):
        """
        判断是否不能处理的路径（回收站、隐藏目录、群晖 @eaDir 等）
        统一为正斜杠后再匹配，兼容 Windows 反斜杠路径。
        """
        if not path:
            return True
        # 统一分隔符；前后补 / 以便匹配段边界（如目录名本身为 @Recycle）
        normalized = path.replace("\\", "/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        if not normalized.endswith("/"):
            normalized = normalized + "/"
        return (
            "/@Recycle/" in normalized
            or "/#recycle/" in normalized
            or "/@eaDir/" in normalized
            or "/@eaDir" in normalized.rstrip("/")  # 路径以 @eaDir 结尾
            or "/." in normalized  # 隐藏目录段（/.xxx/）
        )

    @staticmethod
    def has_incomplete_download_marker(path, depth: int = _INCOMPLETE_SCAN_DEPTH) -> bool:
        """目录内是否存在下载器未完成临时文件（如迅雷 .xltd）."""
        if not path or not os.path.isdir(path):
            return False
        base_depth = os.path.normpath(path).count(os.sep)
        for root, dirs, files in os.walk(path):
            for name in (*dirs, *files):
                if name.lower().endswith(INCOMPLETE_DOWNLOAD_SUFFIXES):
                    return True
            if root.count(os.sep) - base_depth >= depth:
                dirs[:] = []
        return False

    @staticmethod
    def is_incomplete_media_dir(path, exts: list[str] | None = None) -> bool:
        """是否为下载器未完成的媒体目录.

        迅雷等下载器会创建与文件同名的目录（如 ``Movie.mp4/``），下载中的
        ``.xltd`` 与广告小文件混在其中；此类目录在完成前不能进入识别/转移。
        """
        if not path or not os.path.isdir(path):
            return False
        # 迅雷完成后的目录名也可能带媒体后缀（Movie.mp4/）；
        # 只有还存在 .xltd 等未完成标记时才算未完成，不能仅凭后缀判断。
        return PathUtils.has_incomplete_download_marker(path)

    @staticmethod
    def resolve_min_filesize(value=None, default_bytes: int = RMT_MIN_FILESIZE) -> int:
        """把配置中的 MB 数值（int/str）解析为字节；空值返回默认值."""
        raw = str(value if value is not None else "").strip()
        if not raw or raw == "0":
            return default_bytes
        if raw.isdigit():
            return int(raw) * 1024 * 1024
        return default_bytes

    @staticmethod
    def is_path_in_path(path1, path2):
        """
        判断两个路径是否包含关系 path1 in path2
        """
        if not path1 or not path2:
            return False
        path1 = os.path.normpath(path1).replace("\\", "/")
        path2 = os.path.normpath(path2).replace("\\", "/")
        if path1 == path2:
            return True
        path = os.path.dirname(path2)
        while True:
            if path == path1:
                return True
            path = os.path.dirname(path)
            if path == os.path.dirname(path):
                break
        return False

    @staticmethod
    def is_same_filesystem(path1: str, path2: str) -> bool:
        """
        判断两个路径是否位于同一文件系统/分区（同盘）。

        - POSIX：比较 os.stat().st_dev（同一设备号=同文件系统）
        - Windows：比较盘符（os.path.splitdrive）。挂载到子目录的盘可能无法
          通过盘符判断，此时退化为 st_dev 对比。
        判断失败（路径不存在/无权限）时返回 False，由调用方兜底。
        """
        if not path1 or not path2:
            return False
        try:
            # Windows 先按盘符判断（最常见的跨盘场景）
            if os.name == "nt":
                drive1 = os.path.splitdrive(os.path.normpath(path1))[0].upper()
                drive2 = os.path.splitdrive(os.path.normpath(path2))[0].upper()
                if drive1 and drive2:
                    return drive1 == drive2
            # POSIX / Windows 挂载子目录：用 st_dev 对比
            dev1 = os.stat(path1).st_dev
            dev2 = os.stat(path2).st_dev
            return dev1 == dev2
        except OSError:
            return False

    @staticmethod
    def get_bluray_dir(path):
        """
        判断是否蓝光原盘目录，是则返回原盘的根目录，否则返回空
        """
        if not path or not os.path.exists(path):
            return None
        if os.path.isdir(path):
            if os.path.exists(os.path.join(path, "BDMV", "index.bdmv")):
                return path
            elif os.path.normpath(path).endswith("BDMV") and os.path.exists(os.path.join(path, "index.bdmv")):
                return os.path.dirname(path)
            elif os.path.normpath(path).endswith("STREAM") and os.path.exists(
                os.path.join(os.path.dirname(path), "index.bdmv")
            ):
                return PathUtils.get_parent_paths(path, 2)
            else:
                # 电视剧原盘下会存在多个目录形如：Spider Man 2021/DIsc1, Spider Man 2021/Disc2
                for level1 in PathUtils.get_dir_level1_medias(path):
                    if os.path.exists(os.path.join(level1, "BDMV", "index.bdmv")):
                        return path
                return None
        else:
            if (
                str(os.path.splitext(path)[-1]).lower() in [".m2ts", ".ts"]
                and os.path.normpath(os.path.dirname(path)).endswith("STREAM")
                and os.path.exists(os.path.join(PathUtils.get_parent_paths(path, 2), "index.bdmv"))
            ):
                return PathUtils.get_parent_paths(path, 3)
            else:
                return None

    @staticmethod
    def get_parent_paths(path, level: int = 1):
        """
        获取父目录路径，level为向上查找的层数
        """
        for _lv in range(level):
            path = os.path.dirname(path)
        return path

    @staticmethod
    def is_extras(path: str) -> bool:
        """
        判断是否为额外内容/花絮/特别篇目录或文件。
        匹配 BONUS.DISC、behind the scenes、deleted scenes、interviews、
        samples、shorts、featurettes、clips 等模式，
        以及 SP/Specials/Season 0 目录与 SPxx 命名的特别篇文件。
        """
        basedir = os.path.basename(path)
        # 去掉扩展名再匹配一次：`interviews$` / `making of$` 这类以结尾锚定的模式，
        # 对 `interviews.mkv` 永远不生效。目录名无扩展名时 stem == basedir，
        # 两种写法都保留可覆盖 `dir.extras`（目录）与 `extras.mkv`（文件）。
        stem = os.path.splitext(basedir)[0]
        for candidate in (basedir, stem):
            if re.search(
                r".+?[\._ ]BONUS[\._ ]DISC"
                r"|behind[\._ -]the[\._ -]scenes$"
                r"|deleted[\._ -]scenes$"
                r"|interviews$"
                r"|featurettes$"
                r"|making[\._ -]of$"
                r"|gag[\._ -]reel$"
                r"|extras$"
                r"|bonus$"
                r"|samples$"
                r"|shorts$"
                r"|clips$",
                candidate,
                re.IGNORECASE,
            ):
                return True
        if re.search(
            r".+?[\._ ]BONUS[\._ ]DISC[\._ ]"
            r"|.+?SP?\d{1,2}\.extras\.\d{2,}"
            r"|.+?\.extras-\d+\."
            r"|[\._ -]extras[\._ -]",
            basedir,
            re.IGNORECASE,
        ):
            return True
        # 特别篇文件：SP01 / SP12 这类带分隔符界定的标记。
        # 要求两侧都有分隔符（或位于首尾），避免误伤 Spider-Man、Spring 等单词。
        # 例：The.World.at.War.SP09.1973.BluRay...mkv、某某剧.SP03.mkv
        if re.search(r"(?:^|[\._ \-])SP\d{1,2}(?:$|[\._ \-])", basedir, re.IGNORECASE):
            return True
        # 路径段是花絮/特别篇目录：.../Extras/...、.../Bonus Disc/...、.../SP/...、.../Season 0/...
        normalized = path.replace("\\", "/")
        return bool(
            re.search(
                r"/(?:extras|bonus(?:[\._ -]disc)?|featurettes|behind[\._ -]the[\._ -]scenes"
                r"|sp|specials|season[\._ -]?0)/",
                f"{normalized}/",
                re.IGNORECASE,
            )
        )

    @staticmethod
    def get_extras_dir(path: str) -> str | None:
        """如果路径在花絮目录内，返回花絮目录路径。"""
        parent_dir = os.path.dirname(path)
        if PathUtils.is_extras(path):
            return path
        if PathUtils.is_extras(parent_dir):
            return parent_dir
        return None
