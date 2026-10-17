"""新增 NexusPHP 站点配置：可被 SiteEngine 正常加载。"""

from app.sites.engine import SiteEngine

_SITES = {
    "muxuege": ("慕雪阁", "https://pt.muxuege.org"),
    "xingwan": ("星湾", "https://xingwan.cc"),
    "itzmx": ("PT分享站", "https://pt.itzmx.com"),
}


def test_new_site_configs_loaded():
    engine = SiteEngine(definitions_dir="config/sites")
    for sid, (name, domain) in _SITES.items():
        site = engine.get_by_id(sid)
        assert site is not None, sid
        assert site.name == name
        assert site.domain == domain
        assert site.html is not None
        assert (site.html.search.get("params") or {}).get("search") == "{keyword}"
        assert "table.torrents" in ((site.html.torrents.get("list") or {}).get("selector") or "")
