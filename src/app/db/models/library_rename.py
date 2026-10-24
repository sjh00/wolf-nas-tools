"""媒体库批量重命名与库内元数据模型."""

from sqlalchemy import BigInteger, Float, Index, Integer, Sequence, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class LIBRARYRENAMEJOB(Base):
    """批量重命名计划/任务."""

    __tablename__ = "LIBRARY_RENAME_JOB"
    __table_args__ = (
        Index("INDX_LIBRARY_RENAME_JOB_STATUS", "STATUS"),
        Index("INDX_LIBRARY_RENAME_JOB_PLAN", "PLAN_ID", unique=True),
    )

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    PLAN_ID: Mapped[str] = mapped_column(String(64))
    STATUS: Mapped[str] = mapped_column(String(32), default="planned")
    SCOPE: Mapped[str] = mapped_column(Text, default="{}")
    RULE_SNAPSHOT: Mapped[str] = mapped_column(Text, default="{}")
    CREATED_BY: Mapped[int | None] = mapped_column(Integer, nullable=True)
    CREATED_AT: Mapped[str] = mapped_column(String(20), default="")
    STARTED_AT: Mapped[str | None] = mapped_column(String(20), nullable=True)
    FINISHED_AT: Mapped[str | None] = mapped_column(String(20), nullable=True)
    TOTAL: Mapped[int] = mapped_column(Integer, default=0)
    CHANGED: Mapped[int] = mapped_column(Integer, default=0)
    UNCHANGED: Mapped[int] = mapped_column(Integer, default=0)
    SKIPPED: Mapped[int] = mapped_column(Integer, default=0)
    CONFLICT: Mapped[int] = mapped_column(Integer, default=0)
    NEEDS_METADATA: Mapped[int] = mapped_column(Integer, default=0)
    FAILED: Mapped[int] = mapped_column(Integer, default=0)
    DONE: Mapped[int] = mapped_column(Integer, default=0)
    ROLLED_BACK: Mapped[int] = mapped_column(Integer, default=0)


class LIBRARYRENAMEITEM(Base):
    """批量重命名单条计划/执行状态."""

    __tablename__ = "LIBRARY_RENAME_ITEM"
    __table_args__ = (
        UniqueConstraint("JOB_ID", "OLD_PATH_HASH", name="UQ_LIBRARY_RENAME_ITEM_PATH"),
        Index("INDX_LIBRARY_RENAME_ITEM_JOB", "JOB_ID"),
        Index("INDX_LIBRARY_RENAME_ITEM_STATUS", "STATUS"),
    )

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    JOB_ID: Mapped[int] = mapped_column(Integer)
    BACKEND_ID: Mapped[str] = mapped_column(String(64), default="local")
    ROOT: Mapped[str] = mapped_column(String(512), default="")
    OLD_PATH: Mapped[str] = mapped_column(Text)
    NEW_PATH: Mapped[str | None] = mapped_column(Text, nullable=True)
    OLD_PATH_HASH: Mapped[str] = mapped_column(String(64))
    OLD_SIZE: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    OLD_MTIME: Mapped[float | None] = mapped_column(Float, nullable=True)
    METADATA_SOURCE: Mapped[str] = mapped_column(String(64), default="")
    METADATA_SNAPSHOT: Mapped[str] = mapped_column(Text, default="{}")
    ACTION: Mapped[str] = mapped_column(String(32), default="skip")
    STATUS: Mapped[str] = mapped_column(String(32), default="planned")
    DIRECTORY_MOVE_ID: Mapped[str | None] = mapped_column(String(64), nullable=True)
    AUX_MOVES: Mapped[str | None] = mapped_column(Text, nullable=True)
    REASON: Mapped[str | None] = mapped_column(Text, nullable=True)
    ERROR: Mapped[str | None] = mapped_column(Text, nullable=True)
    ROLLBACK_STATUS: Mapped[str | None] = mapped_column(String(32), nullable=True)


class LIBRARYMEDIAMETADATA(Base):
    """库内文件元数据缓存/人工映射."""

    __tablename__ = "LIBRARY_MEDIA_METADATA"
    __table_args__ = (
        UniqueConstraint("BACKEND_ID", "PATH_HASH", name="UQ_LIBRARY_MEDIA_METADATA_PATH"),
        Index("INDX_LIBRARY_MEDIA_METADATA_PATH", "PATH_HASH"),
    )

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    BACKEND_ID: Mapped[str] = mapped_column(String(64), default="local")
    PATH: Mapped[str] = mapped_column(Text)
    PATH_HASH: Mapped[str] = mapped_column(String(64))
    TYPE: Mapped[str] = mapped_column(String(32), default="")
    TITLE: Mapped[str] = mapped_column(String(512), default="")
    YEAR: Mapped[str] = mapped_column(String(16), default="")
    TMDBID: Mapped[str] = mapped_column(String(64), default="")
    SEASON: Mapped[str] = mapped_column(String(32), default="")
    EPISODE: Mapped[str] = mapped_column(String(64), default="")
    SEASON_EPISODE_COUNT: Mapped[int | None] = mapped_column(Integer, nullable=True)
    SOURCE_FILENAME: Mapped[str | None] = mapped_column(String(512), nullable=True)
    METADATA_SOURCE: Mapped[str] = mapped_column(String(64), default="")
    IDENTITY_ID: Mapped[str | None] = mapped_column(String(26), nullable=True, index=True)
    ANCHOR_PROVIDER: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ANCHOR_EXTERNAL_ID: Mapped[str | None] = mapped_column(String(255), nullable=True)
    CONTENT_PROFILE: Mapped[str | None] = mapped_column(String(64), nullable=True)
    METADATA_POLICY: Mapped[str | None] = mapped_column(String(64), nullable=True)
    NAMING_PROFILE: Mapped[str | None] = mapped_column(String(64), nullable=True)
    CONFIDENCE: Mapped[str] = mapped_column(String(16), default="medium")
    IS_MANUAL: Mapped[int] = mapped_column(Integer, default=0)
    FILE_SIZE: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FILE_MTIME: Mapped[float | None] = mapped_column(Float, nullable=True)
    RAW: Mapped[str | None] = mapped_column(Text, nullable=True)
    CREATED_AT: Mapped[str] = mapped_column(String(20), default="")
    UPDATED_AT: Mapped[str] = mapped_column(String(20), default="")
    UPDATED_BY: Mapped[int | None] = mapped_column(Integer, nullable=True)
