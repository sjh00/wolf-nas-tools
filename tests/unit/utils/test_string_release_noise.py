"""发布名噪声剥离与名称相似度。"""

from app.utils import StringUtils


def test_strip_release_noise_removes_bracketed_tags():
    src = "【10月】与暗黑召唤师秘密恋爱中 01【完全无修版】.mp4"
    out = StringUtils.strip_release_noise(src)
    assert "10月" not in out
    assert "完全无修版" not in out
    assert "与暗黑召唤师秘密恋爱中" in out
    assert "01" in out


def test_strip_release_noise_keeps_normal_name():
    assert StringUtils.strip_release_noise("Some Show S01E02 1080p WEB-DL") == "Some Show S01E02 1080p WEB-DL"


def test_similarity_matches_related_names():
    a = "【10月】与暗黑召唤师秘密恋爱中 01【完全无修版】.mp4"
    b = "[完全无修版] 与暗黑召唤师秘密恋爱中 - 01 [简／繁] (1080p H.264 AAC2.0)"
    assert StringUtils.similarity(a, b) > 0.5
    assert StringUtils.similarity(a, "完全不相关的另一个剧集 S01E09") < 0.4
