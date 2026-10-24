"""PluginFrameworkService 单元测试."""

from typing import cast
from unittest.mock import MagicMock, patch

from app.services.plugin_framework_service import PluginFrameworkService


class TestPluginFrameworkServiceGetPluginPath:
    def _service(self, orm_path: str | None = None, registry_path: str | None = None):
        repo = MagicMock()
        orm_model = MagicMock()
        orm_model.PATH = orm_path
        repo.get_manifest_by_id.return_value = orm_model if orm_path is not None else None
        registry = MagicMock()
        registry.get_plugin_path.return_value = registry_path
        return PluginFrameworkService(
            repo=repo,
            menu_repo=MagicMock(),
            role_repo=MagicMock(),
            plugin_registry=registry,
            plugin_sandbox=MagicMock(),
        )

    def test_get_plugin_path_prefers_existing_db_path(self):
        svc = self._service(orm_path="/db/plugins/foo-1.0.0", registry_path="/registry/plugins/foo-1.0.0")
        with patch("app.services.plugin_framework_service.os.path.exists", return_value=True):
            path = svc.get_plugin_path("foo")
        assert path == "/db/plugins/foo-1.0.0"

    def test_get_plugin_path_fallback_when_db_path_missing(self):
        svc = self._service(orm_path="/db/plugins/foo-1.0.0", registry_path="/registry/plugins/foo-1.0.0")
        with patch("app.services.plugin_framework_service.os.path.exists", return_value=False):
            path = svc.get_plugin_path("foo")
        assert path == "/registry/plugins/foo-1.0.0"
        cast(MagicMock, svc._plugin_registry).get_plugin_path.assert_called_once_with("foo")

    def test_get_plugin_path_fallback_when_no_db_record(self):
        svc = self._service(orm_path=None, registry_path="/registry/plugins/foo-1.0.0")
        with patch("app.services.plugin_framework_service.os.path.exists", return_value=False):
            path = svc.get_plugin_path("foo")
        assert path == "/registry/plugins/foo-1.0.0"

    def test_get_plugin_path_returns_none_when_no_path_found(self):
        svc = self._service(orm_path="/db/plugins/foo-1.0.0", registry_path=None)
        with patch("app.services.plugin_framework_service.os.path.exists", return_value=False):
            path = svc.get_plugin_path("foo")
        assert path is None


class TestPluginFrameworkContentProfileDefaults:
    def test_overlay_defaults_without_mutating_manifest(self):
        profiles = [
            {
                "key": "custom",
                "default_search_source": "source_a",
                "default_detail_source": "detail_a",
                "search_sources": [
                    {"label": "Source A", "value": "source_a"},
                    {"label": "Source B", "value": "source_b"},
                ],
            }
        ]
        config = {
            "content_profile_defaults": {
                "custom": {
                    "default_search_source": "source_b",
                    "default_detail_source": "detail_b",
                }
            }
        }
        merged = PluginFrameworkService._apply_content_profile_defaults(profiles, config)
        assert merged[0]["default_search_source"] == "source_b"
        assert merged[0]["default_detail_source"] == "detail_b"
        assert profiles[0]["default_search_source"] == "source_a"

    def test_overlay_ignores_unknown_search_source(self):
        profiles = [
            {
                "key": "custom",
                "default_search_source": "source_a",
                "search_sources": [{"label": "Source A", "value": "source_a"}],
            }
        ]
        config = {"content_profile_defaults": {"custom": {"default_search_source": "unknown"}}}
        merged = PluginFrameworkService._apply_content_profile_defaults(profiles, config)
        assert merged[0]["default_search_source"] == "source_a"
