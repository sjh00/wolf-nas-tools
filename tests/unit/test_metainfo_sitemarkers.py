"""回归测试：meta_info() 入口（媒体搜索）同样剥离站点标记"""

from app.media.parser._metainfo import meta_info


def test_metainfo_bracket_domain():
    mi = meta_info("The.Boys.S04E08.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv")
    assert mi.en_name == "The Boys"
    assert mi.begin_season == 4
    assert mi.begin_episode == 8


def test_metainfo_www_domain():
    mi = meta_info("www.UIndex.org    -    FBI.S08E16.1080p.WEB.h264-ETHEL")
    assert mi.en_name == "Fbi"
    assert mi.begin_season == 8
    assert mi.begin_episode == 16


def test_metainfo_slash_separated_titles_are_not_treated_as_path():
    mi = meta_info(
        "[DBD-Raws][进击的巨人 最终季/Shingeki no Kyojin: The Final Season/"
        "進撃の巨人 The Final Season][01-28TV全集+完结篇+特典映像][1080P]"
        "[BDRip][HEVC-10bit][简繁日双语外挂][FLAC][MKV]"
    )
    assert mi.cn_name == "进击的巨人 最终季"
    assert mi.en_name == "Shingeki No Kyojin: The Final Season"
    assert mi.begin_episode == 1


def test_metainfo_real_path_still_uses_filename():
    mi = meta_info("/tmp/media/肖申克的救赎.1994.mp4")
    assert mi.cn_name == "肖申克的救赎"
    assert mi.year == "1994"
