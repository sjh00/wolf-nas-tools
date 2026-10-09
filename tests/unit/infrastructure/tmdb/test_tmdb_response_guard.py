"""TMDB 响应异常加固测试：空/非 JSON 响应不应导致 NoneType 下标错误。"""

from app.infrastructure.external.tmdbv3api.tmdb import TMDb


def test_get_obj_returns_empty_for_none():
    # result[key] 对 None 会抛 'NoneType' object is not subscriptable，需直接返回空列表
    assert TMDb._get_obj(None) == []


def test_get_obj_returns_empty_for_non_dict():
    assert TMDb._get_obj("error") == []
    assert TMDb._get_obj([1, 2, 3]) == []


def test_get_obj_parses_results():
    items = TMDb._get_obj({"results": [{"id": 1}, {"id": 2}]})
    assert len(items) == 2
    assert getattr(items[0], "id") == 1
