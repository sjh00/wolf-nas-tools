"""插件 backend 包隔离：多个插件不能互相覆盖 backend.*."""

import importlib.util
import sys
from pathlib import Path

from app.plugin_framework.sandbox import PluginSandbox


def _write_plugin(root: Path, value: str, *, absolute: bool = False) -> Path:
    backend = root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "helper.py").write_text(f"VALUE = {value!r}\n", encoding="utf-8")
    imp = "from backend.helper import VALUE" if absolute else "from .helper import VALUE"
    (backend / "plugin.py").write_text(f"{imp}\n\nclass Plugin:\n    value = VALUE\n", encoding="utf-8")
    return backend / "plugin.py"


def test_relative_imports_are_isolated_between_plugins(tmp_path):
    sandbox = object.__new__(PluginSandbox)
    first = _write_plugin(tmp_path / "first", "first")
    second = _write_plugin(tmp_path / "second", "second")

    for plugin_id, file_path in (("first", first), ("second", second)):
        full_name = sandbox._install_plugin_package(plugin_id, str(file_path.parent.parent), "backend.plugin")
        spec = importlib.util.spec_from_file_location(full_name, file_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
        assert module.Plugin.value == plugin_id


def test_absolute_import_plugin_uses_its_own_backend(tmp_path):
    sandbox = object.__new__(PluginSandbox)
    plugin_path = tmp_path / "legacy"
    file_path = _write_plugin(plugin_path, "legacy", absolute=True)
    root_dir = str(file_path.parent)

    assert sandbox._uses_absolute_backend_import(str(plugin_path), "backend") is True
    sandbox._install_entry_root_alias("backend", root_dir)
    full_name = sandbox._install_plugin_package("legacy", str(plugin_path), "backend.plugin")
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)

    assert module.Plugin.value == "legacy"
