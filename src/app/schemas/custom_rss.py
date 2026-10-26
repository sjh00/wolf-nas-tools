"""自定义 RSS 源 API 模型。"""

from pydantic import BaseModel, Field


class CustomRssSourcePayload(BaseModel):
    id: int | None = None
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None
    proxy: bool = False
    cookie: str | None = None
    headers: str | None = Field(default=None, description="JSON 对象字符串")
