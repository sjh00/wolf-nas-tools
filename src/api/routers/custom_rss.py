"""自定义 RSS 源管理接口。"""

from fastapi import APIRouter, Depends

from api.deps import require_permission
from app.schemas.auth import UserContext
from app.schemas.custom_rss import CustomRssSourcePayload
from app.services.rss_automation.custom_source_service import CustomRssSourceService
from app.utils.response import success

router = APIRouter(prefix="/rss-sources")


def get_service() -> CustomRssSourceService:
    return CustomRssSourceService()


@router.get("")
def list_sources(
    svc: CustomRssSourceService = Depends(get_service),
    current_user: UserContext = Depends(require_permission("site:manage")),
):
    return success(data=svc.list(current_user))


@router.post("")
def create_source(
    payload: CustomRssSourcePayload,
    svc: CustomRssSourceService = Depends(get_service),
    current_user: UserContext = Depends(require_permission("site:manage")),
):
    return success(data=svc.create(payload.model_dump(exclude_unset=True), current_user))


@router.put("/{source_id}")
def update_source(
    source_id: int,
    payload: CustomRssSourcePayload,
    svc: CustomRssSourceService = Depends(get_service),
    current_user: UserContext = Depends(require_permission("site:manage")),
):
    return success(data=svc.update(source_id, payload.model_dump(exclude_unset=True), current_user))


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
    svc: CustomRssSourceService = Depends(get_service),
    current_user: UserContext = Depends(require_permission("site:manage")),
):
    return success(data=svc.delete(source_id, current_user))


@router.post("/test")
def test_source(
    payload: CustomRssSourcePayload,
    svc: CustomRssSourceService = Depends(get_service),
    current_user: UserContext = Depends(require_permission("site:manage")),
):
    return success(data=svc.test(payload.model_dump(exclude_unset=True), current_user))
