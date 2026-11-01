"""适配器契约测试：接口声明的每个方法都必须在适配器上真实存在并可调用。

背景（真实故障）：`ITransferHistoryRepository` 之外的
`update_transfer_dest` / `update_transfer_paths` 只实现在 repository，
`TransferHistoryRepositoryAdapter` 没有转发。媒体库一致性校验与作品级跨盘迁移
调用时抛 AttributeError——但单测全部用 MagicMock 替身，测试仍然通过。

这类「接口与适配器脱节」用 mock 发现不了，只能对真实适配器做契约断言。
"""

import inspect
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.transfer import TRANSFERHISTORY
from app.db.repositories.transfer_repo_adapter import TransferHistoryRepositoryAdapter
from app.db.repositories.transfer_repository import TransferRepository
from app.db.session import SessionManager
from app.domain.interfaces.transfer_repo import ITransferHistoryRepository


@pytest.fixture
def adapter_with_db():
    """真实 sqlite + 真实适配器（不 mock 仓储）。

    session manager 挂在 **repository 实例**上而非 BaseRepository 类属性：
    类属性是全局状态，与其它测试并行/交替执行时会互相覆盖
    （表现为单独跑通过、全量跑失败）。
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    mgr = SessionManager()
    mgr._engine = engine
    mgr._factory = sessionmaker(bind=engine, expire_on_commit=False)

    repo = TransferRepository()
    repo._session_manager = mgr
    adapter = TransferHistoryRepositoryAdapter(repo=repo)

    with mgr.session_scope() as db:
        db.add(
            TRANSFERHISTORY(
                MODE="link",
                TYPE="movie",
                CATEGORY="华语电影",
                TMDBID=801803,
                TITLE="独行月球",
                YEAR="2022",
                SEASON_EPISODE="",
                SOURCE="目录同步",
                SOURCE_PATH="/src/movie",
                SOURCE_FILENAME="a.mkv",
                DEST="/lib",
                DEST_PATH="/lib/old",
                DEST_FILENAME="old.mkv",
                DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    try:
        yield adapter, mgr
    finally:
        engine.dispose()


class TestAdapterImplementsInterface:
    def test_all_interface_methods_present(self):
        """接口声明的每个方法，适配器都必须有实现。

        漏实现会在运行期才暴露，且被 MagicMock 掩盖，故在此静态兜住。
        """
        abstract = {
            name
            for name, _ in inspect.getmembers(ITransferHistoryRepository, inspect.isfunction)
            if not name.startswith("_")
        }
        missing = [name for name in sorted(abstract) if not hasattr(TransferHistoryRepositoryAdapter, name)]
        assert not missing, f"适配器未实现接口方法: {missing}"


class TestTransferPathUpdates:
    """媒体库一致性校验 / 作品级跨盘迁移依赖的路径回写。"""

    def test_update_transfer_dest_persists(self, adapter_with_db):
        adapter, mgr = adapter_with_db
        assert adapter.update_transfer_dest(logid=1, new_dest_path="/lib/new", new_dest_filename="new.mkv")
        with mgr.session_scope() as db:
            row = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == 1).first()
            assert row.DEST_PATH == "/lib/new"
            assert row.DEST_FILENAME == "new.mkv"

    def test_update_transfer_paths_persists(self, adapter_with_db):
        adapter, mgr = adapter_with_db
        assert adapter.update_transfer_paths(
            logid=1,
            new_source_path="/src/new",
            new_source_filename="b.mkv",
            new_dest_path="/lib/final",
            new_dest_filename="final.mkv",
        )
        with mgr.session_scope() as db:
            row = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == 1).first()
            assert row.SOURCE_PATH == "/src/new"
            assert row.SOURCE_FILENAME == "b.mkv"
            assert row.DEST_PATH == "/lib/final"
            assert row.DEST_FILENAME == "final.mkv"

    def test_update_missing_record_returns_false(self, adapter_with_db):
        adapter, _mgr = adapter_with_db
        assert adapter.update_transfer_dest(logid=999, new_dest_path="/x", new_dest_filename="x.mkv") is False
