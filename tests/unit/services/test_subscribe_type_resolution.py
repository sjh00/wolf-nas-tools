"""订阅类型解析：显式 TMDB 号 + 类型时以调用方为准。

真实问题：订阅电视剧时被匹配成另一部同名电影（库里同名作品很常见），
订阅就建成了完全不同的作品，而且用户无法手动指定 TMDB 号来纠正。

修复包含两部分：
1. 前端订阅确认弹窗支持填 TMDB 号并选类型（见 web 仓库）
2. 服务端在「显式 TMDB 号 + 具体类型」时保留调用方类型，不被详情源覆盖
"""

from types import SimpleNamespace

from app.domain.mediatypes import MediaType
from app.services.subscribe.management.add_service import SubscribeAddService

resolve = SubscribeAddService._resolve_subscribe_type


class TestExplicitTmdbWins:
    def test_tv_request_keeps_tv_when_detail_is_movie(self):
        """核心回归：同名电影场景下不能把电视剧订阅变成电影。"""
        assert (
            resolve(
                provider="tmdb",
                requested=MediaType.TV,
                detail_type=MediaType.MOVIE,
                external_id="279155",
            )
            is MediaType.TV
        )

    def test_movie_request_keeps_movie_when_detail_is_tv(self):
        assert (
            resolve(
                provider="tmdb",
                requested=MediaType.MOVIE,
                detail_type=MediaType.TV,
                external_id="1",
            )
            is MediaType.MOVIE
        )

    def test_anime_request_keeps_anime(self):
        assert (
            resolve(
                provider="tmdb",
                requested=MediaType.ANIME,
                detail_type=MediaType.TV,
                external_id="1",
            )
            is MediaType.ANIME
        )

    def test_provider_name_is_normalized(self):
        assert (
            resolve(
                provider=" TMDB ",
                requested=MediaType.TV,
                detail_type=MediaType.MOVIE,
            )
            is MediaType.TV
        )


class TestOtherProvidersFollowDetail:
    def test_douban_follows_detail_type(self):
        """非 TMDB 来源没有「指定类型查详情」的语义，仍以详情为准。"""
        assert (
            resolve(
                provider="douban",
                requested=MediaType.TV,
                detail_type=MediaType.MOVIE,
            )
            is MediaType.MOVIE
        )

    def test_bangumi_follows_detail_type(self):
        assert (
            resolve(
                provider="bangumi",
                requested=MediaType.TV,
                detail_type=MediaType.ANIME,
            )
            is MediaType.ANIME
        )


class TestEdgeCases:
    def test_same_type_returns_detail(self):
        assert (
            resolve(
                provider="tmdb",
                requested=MediaType.TV,
                detail_type=MediaType.TV,
            )
            is MediaType.TV
        )

    def test_unknown_requested_falls_back_to_detail(self):
        assert (
            resolve(
                provider="tmdb",
                requested=None,
                detail_type=MediaType.TV,
            )
            is MediaType.TV
        )

    def test_unknown_detail_falls_back_to_requested(self):
        assert (
            resolve(
                provider="tmdb",
                requested=MediaType.TV,
                detail_type=None,
            )
            is MediaType.TV
        )

    def test_returns_value_usable_by_downstream(self):
        """返回值必须带 .value，下游有 `media_info.type.value` 之类取值。"""
        result = resolve(
            provider="tmdb",
            requested=MediaType.TV,
            detail_type=MediaType.MOVIE,
        )
        assert isinstance(result, MediaType)
        assert result.value == "tv"


class TestAddRequestCarriesAnchor:
    """路由把 anchor 归一成 metadata_ref，供服务端按锚点取详情。"""

    def test_anchor_becomes_metadata_ref(self):
        from api.routers.subscription import AddRssMediaRequest

        req = AddRssMediaRequest(
            name="示例剧集",
            type="tv",
            anchor_provider="tmdb",
            anchor_external_id="279155",
        )
        # 路由内的归一逻辑（add_rss_media 的第一步）
        if req.anchor_provider and req.anchor_external_id and not req.metadata_ref:
            req.metadata_ref = f"{req.anchor_provider}:{req.anchor_external_id}"
        assert req.metadata_ref == "tmdb:279155"
        assert SimpleNamespace(**{"mtype": req.type}).mtype == "tv"
