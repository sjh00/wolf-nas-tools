"""媒体库目录路由配置测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.media_library_service import MediaLibraryService


def test_duplicate_directory_route_is_rejected():
    service = MediaLibraryService.__new__(MediaLibraryService)
    service._route_repo = MagicMock()
    service._route_repo.list.return_value = [
        SimpleNamespace(id=1, content_profile="", target_path="/media", server_id=1)
    ]
    service._media_server = MagicMock()
    service._media_server.get_server_options.return_value = [{"id": 1, "name": "普通 Emby"}]

    with pytest.raises(ValueError, match="已存在"):
        service.save_route({"target_path": "/media", "server_id": 1})
