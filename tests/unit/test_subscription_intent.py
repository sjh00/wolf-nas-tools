from app.services.metadata_service import MetadataService
from app.services.subscription_intent import resolve_subscription


def test_resolve_subscription_builtin_formats():
    MetadataService(register_builtins=True)._ensure_builtin()
    tmdb = resolve_subscription("tmdb", "278", "肖申克的救赎")
    douban = resolve_subscription("douban", "1292052", "肖申克的救赎")
    bangumi = resolve_subscription("bangumi", "400602", "葬送的芙莉莲")
    assert tmdb and tmdb.mediaid == "278" and tmdb.metadata_ref is None
    assert douban and douban.mediaid == "DB:1292052"
    assert bangumi and bangumi.mediaid == "BG:400602"
    assert bangumi.content_profile == "anime"
    assert bangumi.media_type.value == "tv"
    assert resolve_subscription("unknown", "1", "x") is None


def test_parse_media_ref_uses_descriptor_formats():
    from app.media.metadata.refs import parse_media_ref

    MetadataService(register_builtins=True)._ensure_builtin()
    assert parse_media_ref("DB:1292052") == ("douban", "1292052")
    assert parse_media_ref("BG:400602") == ("bangumi", "400602")
    assert parse_media_ref("278") == ("tmdb", "278")
    assert parse_media_ref("TMDB:278") == ("tmdb", "278")
