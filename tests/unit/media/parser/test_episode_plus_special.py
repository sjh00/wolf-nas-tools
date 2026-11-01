"""集号 + 特别篇（14+sp14）解析回归测试。

回归：`[14+sp14]` 曾被解析为无集数（begin_episode=None），被订阅流程当作整季处理，
导致订阅提前判定完成。
"""

from app.media import meta_info


def test_bracket_episode_plus_special():
    info = meta_info("[悠哈璃羽字幕社][药屋少女的呢喃][14+sp14][1080p][CHT&JP]")
    assert info.begin_episode == 14
    assert info.get_episode_list() == [14]


def test_bracket_episode_plus_special_two_digit():
    info = meta_info("[悠哈璃羽字幕社][药屋少女的呢喃/独语][06+sp06][1080p][CHS&JP]")
    assert info.begin_episode == 6


def test_bare_episode_plus_special():
    info = meta_info("药屋少女的呢喃 14+sp14 1080p")
    assert info.begin_episode == 14
