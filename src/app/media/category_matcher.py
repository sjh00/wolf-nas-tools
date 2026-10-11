"""分类匹配工具函数"""


def get_category(categorys, tmdb_info):
    """
    根据 TMDB 信息与分类配置进行比较，确定所属分类
    :param categorys: 分类配置 dict[str, dict[str, str]]
    :param tmdb_info: TMDB 信息
    :return: 分类的名称
    """
    if not tmdb_info:
        return ""
    if not categorys:
        return ""
    # 空规则分类视为“兜底”，但**不立即返回**：先按顺序匹配所有带规则的分类，
    # 全部未命中时再落到第一个空规则分类。避免“兜底/默认分类排在前面时吞掉后续精确分类”
    # （如空规则的「华语电影」排在「外语电影」之前，导致外语片被归入华语目录）。
    fallback = ""
    for key, item in categorys.items():
        if not item:
            if not fallback:
                fallback = key
            continue
        match_flag = True
        for attr, value in item.items():
            if not value:
                continue
            info_value = tmdb_info.get(attr)
            if not info_value:
                match_flag = False
                continue
            elif attr == "production_countries":
                info_values = [str(val.get("iso_3166_1")).upper() for val in info_value]
            else:
                if isinstance(info_value, list):
                    info_values = [str(val).upper() for val in info_value]
                else:
                    info_values = [str(info_value).upper()]

            if value.find(",") != -1:
                values = [str(val).upper() for val in value.split(",")]
            else:
                values = [str(value).upper()]

            if not set(values).intersection(set(info_values)):
                match_flag = False
        if match_flag:
            return key
    return fallback
