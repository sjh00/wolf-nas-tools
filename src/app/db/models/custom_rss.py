"""用户自定义 RSS 源模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Sequence, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class CustomRssSource(Base):
    __tablename__ = "CUSTOM_RSS_SOURCE"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    USER_ID: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("RBAC_USERS.ID", ondelete="CASCADE"), nullable=True, index=True
    )
    NAME: Mapped[str] = mapped_column(String(255), nullable=False)
    URL: Mapped[str] = mapped_column(Text, nullable=False)
    ENABLED: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    PROXY: Mapped[bool] = mapped_column(Boolean, default=False)
    COOKIE: Mapped[str | None] = mapped_column(Text, nullable=True)
    HEADERS: Mapped[str | None] = mapped_column(Text, nullable=True)
    LAST_FETCH_AT: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    LAST_SUCCESS_AT: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    LAST_ERROR: Mapped[str | None] = mapped_column(Text, nullable=True)
    ITEM_COUNT: Mapped[int] = mapped_column(Integer, default=0)
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
