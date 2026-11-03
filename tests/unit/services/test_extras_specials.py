"""特别篇（SP）归档到 extras。

媒体库的 extras 机制本来就有：PathUtils.is_extras 命中时，转移会给
media.note["is_extras"] 打标记，path_resolver 把季目录固定为 extras/。

但 SP 命名的特别篇从未被该规则覆盖（只认 BONUS.DISC / extras / featurettes 等
英文关键词），于是 SP 目录里的文件被当成正片：SP09 解析出集号 9，
直接覆盖了正片 S01E09 的位置——《示例剧集》就这样丢了 6 集正片，
媒体库里 E04/E05/E06/E08/E09/E10 实际是 SP 特别篇。

本模块锁定三件事：
1. SP 目录与 SPxx 文件名识别为 extras
2. 普通剧集、以及 Spider-Man 这类包含 sp 的片名不被误判
3. extras 内的特别篇文件名保留 SP 标识，不与正片集号混淆
"""

import pytest

from app.services.transfer.path_resolver import extras_sp_label
from app.utils.path_utils import PathUtils


class TestSpecialsRecognizedAsExtras:
    @pytest.mark.parametrize(
        "path",
        [
            # SP 目录
            "/btstore/tv/Show/SP/The.World.at.War.SP01.mkv",
            # SP 编号文件名（两侧分隔符）
            "/btstore/documentory/战争中的世界/The.World.at.War.SP09.1973.BluRay.mkv",
            "某某剧.SP03.mkv",
            "某某剧_SP03_1080p.mkv",
            "某某剧 - SP12 - 第12集.mkv",
            # 其他特别篇目录写法
            "/btstore/tv/Show/Specials/ep01.mkv",
            "/btstore/tv/Show/Season 0/ep01.mkv",
            "/btstore/tv/Show/Season.0/ep01.mkv",
        ],
    )
    def test_specials_are_extras(self, path):
        assert PathUtils.is_extras(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "interviews.mkv",
            "featurettes.mkv",
            "making of.mkv",
            "bonus.mkv",
            "samples.mkv",
            "clips.mkv",
        ],
    )
    def test_keyword_suffix_works_with_extension(self, path):
        # `interviews$` 这类结尾锚定模式对 `interviews.mkv` 原本永不生效
        assert PathUtils.is_extras(path) is True


class TestNoFalsePositives:
    @pytest.mark.parametrize(
        "path",
        [
            # 正片集，必须留在 Season 目录
            "/btstore/tv/Show/The.World.at.War.E09.1973.BluRay.mkv",
            "/btstore/tv/Show/Show.S01E01.1080p.mkv",
            # 含 sp 字母的普通片名
            "/btstore/tv/Show/Spider-Man.No.Way.Home.2021.mkv",
            "/btstore/tv/Show/Spring.Story.2023.mkv",
            "/btstore/tv/Show/Spy.Kids.2001.mkv",
            "/btstore/tv/Show/The.Spirit.of.the.Beehive.mkv",
            # 中文剧名含「特别」但不是 SP 标记
            "/btstore/tv/Show/特别的她.S01E01.mkv",
            # Special Edition 是版本描述，不是特别篇目录
            "/btstore/tv/Show/Show.S02E05.Special.Edition.mkv",
        ],
    )
    def test_normal_episodes_not_extras(self, path):
        assert PathUtils.is_extras(path) is False

    def test_extras_dir_detection_unchanged(self):
        # 既有行为不能回退：extras 目录与其内部文件都算 extras
        assert PathUtils.is_extras("/tv/Show/extras/clip.mkv") is True
        assert PathUtils.is_extras("/tv/Show/extras") is True


class TestExtrasSpLabel:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("The.World.at.War.SP09.1973.BluRay.1080p.x265.mkv", "SP09"),
            ("The.World.at.War.SP01.1973.mkv", "SP01"),
            ("某某剧.SP12.mkv", "SP12"),
            ("某某剧_SP03_1080p.mkv", "SP03"),
            ("某某剧 - SP05 - 第5集.mkv", "SP05"),
        ],
    )
    def test_extracts_label(self, name, expected):
        assert extras_sp_label(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "Show.S01E09.mkv",
            "Spider-Man.No.Way.Home.2021.mkv",
            "Spring.Story.mkv",
            "The.World.at.War.E09.mkv",
            "",
        ],
    )
    def test_non_specials(self, name):
        assert extras_sp_label(name) == ""

    def test_zero_pads_single_digit(self):
        # SP1 与 SP01 归一化，避免同剧两种写法生成两个文件
        assert extras_sp_label("Show.SP1.mkv") == "SP01"


class TestExtrasPathNaming:
    """extras 内的特别篇文件名必须带 SP 标识，不能渲染成 S01Exx。"""

    @staticmethod
    def _resolve(org_string: str, monkeypatch):
        from types import SimpleNamespace

        from app.domain.mediatypes import MediaType
        from app.services.transfer.path_resolver import TransferPathResolver

        resolver = TransferPathResolver(
            tv_dir_rmt_format="{title}",
            tv_season_rmt_format="Season {season:02d}",
            tv_file_rmt_format="{title} - S{season:02d}E{episode:02d}",
        )
        monkeypatch.setattr(
            resolver,
            "get_format_dict",
            lambda *a, **k: {"title": "示例剧集", "season": 1, "episode": 9},
        )
        media = SimpleNamespace(type=MediaType.TV, org_string=org_string, note={"is_extras": True})
        dir_name, season_name, file_name = TransferPathResolver.get_tv_dest_path(resolver, media, None, None)
        return dir_name, season_name, file_name

    def test_special_uses_sp_label(self, monkeypatch):
        _dir, season, fname = self._resolve("The.World.at.War.SP09.1973.BluRay.1080p.mkv", monkeypatch)
        assert season == "extras"
        assert "SP09" in fname
        # 不能出现 S01E09，否则 extras 里看起来就是正片
        assert "S01E09" not in fname
        assert fname.endswith(".mkv")

    def test_non_special_extras_keeps_original_naming(self, monkeypatch):
        _dir, season, fname = self._resolve("behind the scenes.mkv", monkeypatch)
        assert season == "extras"
        assert fname == "示例剧集 - S01E09"
