"""中文处理工具函数."""

import opencc

# 用 t2s（繁体 → 简体）而不是 tw2sp（台湾正体 → 简体含词汇转换）。
# tw2sp 会先把「台湾异体字」规范回台湾标准字形，导致已经是简体的常用字被改错：
#   么→幺（什么/怎么/那么/为什么 全部中招）、著→着（著名→着名）、
#   埠→端口（蚌埠→蚌端口）、抬→擡（抬→抬的繁体形）、矽→硅。
# 拿 GB2312 一级字表逐字实测：tw2sp 改写 6 个字、hk2s 2 个、t2s 1 个，
# 且 t2s 那 1 个（乾→干）是带词组的正确转换（乾杯→干杯、乾燥→干燥），
# 专名「乾隆/乾坤」仍保留。媒体标题里的台湾用词转换没有价值，不值得付出这个代价。
_to_simplified = opencc.OpenCC("t2s")


def to_simplified(text: str | None) -> str:
    """将繁体中文转换为简体中文.

    :param text: 输入文本
    :return: 简体中文文本；输入为空时返回空字符串
    """
    if not text:
        return ""
    return _to_simplified.convert(text)
