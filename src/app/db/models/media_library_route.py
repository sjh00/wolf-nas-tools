"""内容画像到媒体服务器实例的路由模型。"""

from sqlalchemy import Boolean, ForeignKey, Integer, Sequence, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class MediaLibraryRoute(Base):
    __tablename__ = "MEDIA_LIBRARY_ROUTE"

    ID: Mapped[int] = mapped_column(Integer, Sequence("ID"), primary_key=True)
    CONTENT_PROFILE: Mapped[str] = mapped_column(String(64), default="", index=True)
    TARGET_PATH: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    SERVER_ID: Mapped[int] = mapped_column(Integer, ForeignKey("MEDIASERVER.ID", ondelete="CASCADE"))
    BACKEND_ID: Mapped[str] = mapped_column(String(64), default="local", server_default="local")
    LIBRARY_ID: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ENABLED: Mapped[bool] = mapped_column(Boolean, default=True)
    NOTE: Mapped[str] = mapped_column(Text, default="")
