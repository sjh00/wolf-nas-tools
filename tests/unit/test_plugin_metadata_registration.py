"""插件 manifest 元数据声明与 context 注册测试."""

from unittest.mock import MagicMock

import pytest

from app.media.metadata import ProviderDescriptor, ProviderRef
from app.media.metadata.naming import NamingField, NamingProfile
from app.media.metadata.registry import registry as metadata_registry
from app.plugin_framework.context import PluginContext
from app.schemas.plugin import PluginManifest, PluginMetadataConfig


class _DemoProvider:
    descriptor = ProviderDescriptor(provider_key="demo-provider", display_name="Demo")

    def detail(self, ref, ctx):
        return None


def test_manifest_parses_metadata_declarations():
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "backend": {
                "metadata": {
                    "providers": ["demo-provider"],
                    "naming_profiles": [{"key": "demo-naming"}],
                }
            },
        }
    )

    assert manifest.backend.metadata.keys("providers") == {"demo-provider"}
    assert manifest.backend.metadata.keys("naming_profiles") == {"demo-naming"}
    assert manifest.to_dict()["backend"]["metadata"]["providers"] == [{"key": "demo-provider"}]


def test_context_registers_and_unregisters_declared_metadata():
    manifest = PluginMetadataConfig.from_dict(
        {
            "providers": [{"key": "demo-provider"}],
            "naming_profiles": [{"key": "demo-naming"}],
        }
    )
    ctx = PluginContext("demo-plugin", message=MagicMock(), manifest_metadata=manifest)
    try:
        ctx.register_metadata_provider("demo-provider", _DemoProvider())
        profile = NamingProfile(
            key="demo-naming",
            content_profile="default",
            fields=(NamingField(key="demo.field", label="Demo"),),
        )
        ctx.register_naming_profile("demo-naming", profile)

        assert metadata_registry.get_provider("demo-provider") is not None
        assert metadata_registry.get_profile("naming", "demo-naming") is not None

        ctx.unregister_all_metadata()

        assert metadata_registry.get_provider("demo-provider") is None
        assert metadata_registry.get_profile("naming", "demo-naming") is None
    finally:
        metadata_registry.unregister_plugin("demo-plugin")


def test_context_rejects_undeclared_metadata_key():
    ctx = PluginContext(
        "demo-plugin-2",
        message=MagicMock(),
        manifest_metadata=PluginMetadataConfig.from_dict({"providers": [{"key": "allowed"}]}),
    )
    try:
        with pytest.raises(ValueError, match="未在 manifest 声明"):
            ctx.register_metadata_provider("other", _DemoProvider())
    finally:
        metadata_registry.unregister_plugin("demo-plugin-2")


def test_registry_ref_import_smoke():
    # 确保测试模块中的 ProviderRef 可用，防止回归时误删导入
    assert ProviderRef(provider="x", external_id="1").provider == "x"


def test_context_runs_metadata_cleanup_callbacks():
    ctx = PluginContext("demo-plugin-3", message=MagicMock())
    cleanup = MagicMock()
    ctx.register_metadata_cleanup(cleanup)

    ctx.unregister_all_metadata()

    cleanup.assert_called_once()


def test_registry_calls_provider_unregister_hook():
    calls = []

    class _ProviderWithHook(_DemoProvider):
        descriptor = ProviderDescriptor(provider_key="demo-hook", display_name="Demo")

        def on_unregister(self, plugin_id):
            calls.append(plugin_id)

    metadata_registry.register_provider(_ProviderWithHook(), plugin_id="demo-plugin-4")
    metadata_registry.unregister_plugin("demo-plugin-4")

    assert calls == ["demo-plugin-4"]


def test_private_pack_requires_private_provider_visibility():
    from app.media.metadata import ProviderCapability

    private_manifest = PluginMetadataConfig.from_dict(
        {"visibility": "private", "required_permission": "metadata:private:view", "providers": [{"key": "p"}]}
    )
    ctx = PluginContext("demo-private", message=MagicMock(), manifest_metadata=private_manifest)

    class _PublicProvider:
        descriptor = ProviderDescriptor(
            provider_key="p",
            display_name="p",
            capabilities=frozenset({ProviderCapability.DETAIL}),
            visibility="public",
        )

    try:
        with pytest.raises(ValueError, match="visibility=private"):
            ctx.register_metadata_provider("p", _PublicProvider())
    finally:
        metadata_registry.unregister_plugin("demo-private")


def test_private_pack_injects_required_permission():
    from app.media.metadata import ProviderCapability

    manifest = PluginMetadataConfig.from_dict(
        {
            "visibility": "private",
            "required_permission": "custom:private:view",
            "providers": [{"key": "private-demo"}],
        }
    )
    ctx = PluginContext("demo-private-2", message=MagicMock(), manifest_metadata=manifest)

    class _PrivateProvider:
        descriptor = ProviderDescriptor(
            provider_key="private-demo",
            display_name="private",
            capabilities=frozenset({ProviderCapability.DETAIL}),
            visibility="private",
        )

    try:
        ctx.register_metadata_provider("private-demo", _PrivateProvider())
        provider = metadata_registry.get_provider("private-demo")
        assert provider is not None
        assert provider.descriptor.required_permission == "custom:private:view"
    finally:
        metadata_registry.unregister_plugin("demo-private-2")
