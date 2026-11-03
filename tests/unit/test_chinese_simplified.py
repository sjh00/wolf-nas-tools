"""繁体→简体转换不得改坏已经是简体的常用字。

真实故障：《好像也没那么热血沸腾》解析出的中文名变成
「好像也没那幺热血沸腾」——「么」被转成「幺」，TMDB 用错名搜索查不到
（该条 TRANSFER_HISTORY 的 TMDBID=0），最终带着错误元数据入库。

根因：`opencc.OpenCC("tw2sp")` 会先把「台湾异体字」规范回台湾标准字形，
而「么」在台湾标准里正是「幺」的异体。同一机制还会把
著名→着名、蚌埠→蚌端口、抬→擡、矽→硅。
"""

import pytest

from app.utils.chinese_utils import to_simplified

# GB2312 一级汉字中被 tw2sp 改写的 6 个「已简体」字（逐字实测所得）
_TW2SP_DAMAGED = ["么", "著", "埠", "抬", "矽", "乾"]


@pytest.mark.parametrize(
    "text",
    [
        "好像也没那么热血沸腾",
        "什么是爱",
        "怎么样",
        "为什么是他",
        "干什么",
        "多么美丽",
        "要么这样",
        "著名导演",
        "蚌埠",
        "抬头",
    ],
)
def test_simplified_text_is_unchanged(text):
    """已经是简体、含「么/著/埠/抬」的标题必须原样返回。"""
    assert to_simplified(text) == text


@pytest.mark.parametrize(
    ("traditional", "expected"),
    [
        ("關於我和鬼變成家人的那件事", "关于我和鬼变成家人的那件事"),
        ("當男人戀愛時", "当男人恋爱时"),
        ("誰先愛上他的", "谁先爱上他的"),
        ("他們為什麼要這樣", "他们为什么要这样"),
        ("這樣怎麼行", "这样怎么行"),
        ("瀑布", "瀑布"),
        ("孤味", "孤味"),
    ],
)
def test_traditional_is_converted(traditional, expected):
    assert to_simplified(traditional) == expected


@pytest.mark.parametrize(("raw", "expected"), [("乾杯", "干杯"), ("乾燥", "干燥")])
def test_qian_converts_in_common_words(raw, expected):
    assert to_simplified(raw) == expected


@pytest.mark.parametrize("proper_noun", ["乾隆", "乾坤"])
def test_qian_kept_in_proper_nouns(proper_noun):
    """专名「乾隆/乾坤」不得变成「干隆/干坤」。"""
    assert to_simplified(proper_noun) == proper_noun


def test_no_simplified_char_is_damaged():
    """回归防线：GB2312 一级字表里，只有「乾」允许被改写（词组驱动）。"""
    chars = []
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    damaged = sorted({ch for ch in chars if to_simplified(ch) != ch})
    assert damaged == ["乾"], f"简体常用字被改坏: {damaged}"

    for ch in _TW2SP_DAMAGED:
        if ch == "乾":
            continue
        assert to_simplified(ch) == ch


def test_empty_input():
    assert to_simplified(None) == ""
    assert to_simplified("") == ""
