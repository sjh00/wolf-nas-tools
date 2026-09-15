"""「正在下载」列表端到端：真实数据库 + 真实仓储 + 模拟下载器。

单元测试 mock 掉了仓储，无法覆盖「ORM → 实体 → 服务」这条链路
（例如实体字段名与 ORM 列名不匹配时单测仍会通过）。这里用真实 sqlite
建表写入记录，验证记录能一路出现在列表里。
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.download import DOWNLOADHISTORY
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.db.session import SessionManager
from app.services.download_service import DownloadService

_PUSHED_HASH = "4def530771e85891c8b3411d4ed644bea7d0bde3"
_PUSHED_NAME = "Boyhood 2014 2160p HDR UHD BluRay DTS-HD MA 5.1 x265-10bit-HDS"


@pytest.fixture
def db_env():
    """真实 sqlite（内存）+ 已建表 + 一条 downloading 记录。

    注意：这里替换的是 BaseRepository 的**类属性**（全局生效），必须在用例结束后
    还原，否则会把内存库泄漏给其它测试（表现为无关测试大面积失败）。
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    mgr = SessionManager()
    mgr._engine = engine
    mgr._factory = sessionmaker(bind=engine, expire_on_commit=False)

    import app.db.repositories.download_repository as repo_mod

    base_cls = repo_mod.BaseRepository
    adapter_cls = DownloadHistoryRepositoryAdapter
    saved = getattr(base_cls, "_session_manager", None)

    # 服务与仓储都指向同一内存库（setattr 避免访问私有类属性）
    setattr(adapter_cls, "_session_manager", mgr)
    setattr(base_cls, "_session_manager", mgr)

    with mgr.session_scope() as db:
        db.add(
            DOWNLOADHISTORY(
                USER_ID=1,
                TITLE="少年时代",
                YEAR="2014",
                TYPE="movie",
                TMDBID="85350",
                SE="",
                VOTE="7.5",
                POSTER="/poster.jpg",
                OVERVIEW="",
                TORRENT=_PUSHED_NAME,
                ENCLOSURE="",
                SITE="HDSky",
                DESC="",
                DOWNLOADER="2",
                DOWNLOAD_ID=_PUSHED_HASH,
                SAVE_PATH="/downloads",
                STATE="downloading",
                DATE="2026-09-15 14:44:00",
            )
        )
    try:
        yield mgr
    finally:
        # 还原全局类属性，避免污染其它测试
        if saved is None:
            try:
                delattr(base_cls, "_session_manager")
            except AttributeError:
                pass
        else:
            setattr(base_cls, "_session_manager", saved)
        try:
            delattr(adapter_cls, "_session_manager")
        except AttributeError:
            pass
        engine.dispose()


def _service(progress=None):
    client = MagicMock()
    client.get_downloading_progress.return_value = progress
    cfg = {"id": "2", "name": "qBittorrent", "type": "qbittorrent", "enabled": 1}
    downloader = MagicMock()
    downloader.get_downloader_conf.side_effect = lambda did=None: cfg if did else {"2": cfg}
    downloader.get_downloader.return_value = client
    return (
        DownloadService(
            downloader=downloader,
            searcher=MagicMock(),
            media_service=MagicMock(),
            sites=MagicMock(),
            site_engine=MagicMock(),
            indexer_service=MagicMock(),
            torrent_remover=MagicMock(),
            download_history_repo=DownloadHistoryRepositoryAdapter(),
        ),
        client,
    )


def _read_state(mgr) -> str | None:
    with mgr.session_scope() as db:
        row = db.query(DOWNLOADHISTORY).filter(DOWNLOADHISTORY.DOWNLOAD_ID == _PUSHED_HASH).first()
        return row.STATE if row else None


class TestDownloadingEndToEnd:
    def test_pushed_task_with_progress_is_listed(self, db_env):
        """真实库里写入的 downloading 记录 + 下载器命中 → 出现在列表中并被富化"""
        svc, _client = _service(
            progress=[
                {
                    "id": _PUSHED_HASH,
                    "name": _PUSHED_NAME,
                    "progress": 12.5,
                    "state": "Downloading",
                    "speed": "1MB/s",
                }
            ]
        )

        result = svc.get_downloading_with_media_info()

        assert result["total"] == 1, "平台推送的任务必须出现在「正在下载」列表里"
        item = result["items"][0]
        assert item["id"] == _PUSHED_HASH
        assert item["progress"] == 12.5
        # 用本地记录富化标题（含年份）
        assert "少年时代" in item["title"]
        assert item["downloader_name"] == "qBittorrent"
        # 状态保持 downloading
        assert _read_state(db_env) == "downloading"

    def test_query_failure_keeps_record_downloading(self, db_env):
        """下载器查询失败 → 不展示、也不改状态"""
        svc, client = _service(progress=None)
        client.get_downloading_progress.return_value = None

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        assert _read_state(db_env) == "downloading", "查询失败不得把任务标记为完成"

    def test_completed_progress_exits_list(self, db_env):
        """进度 100% → 退出列表并标记完成"""
        svc, _client = _service(
            progress=[{"id": _PUSHED_HASH, "name": _PUSHED_NAME, "progress": 100.0, "state": "Uploading"}]
        )

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        assert _read_state(db_env) == "completed"

    def test_missing_in_downloader_marked_completed(self, db_env):
        """下载器里查不到该 hash → 按完成处理（清掉幽灵条目）"""
        svc, _client = _service(progress=[])

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        assert _read_state(db_env) == "completed"

    def test_queries_by_pushed_hash_only(self, db_env):
        """只按平台推送的 hash 查询（全量拉取会导致接口超时）"""
        svc, client = _service(progress=[])

        svc.get_downloading_with_media_info()

        assert client.get_downloading_progress.call_args.kwargs.get("ids") == [_PUSHED_HASH]
