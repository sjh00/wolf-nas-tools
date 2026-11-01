"""私有插件打包脚本（zip）.

用法：
    uv run python scripts/pack_private_plugin.py <plugin_dir> <output.zip>

要求 manifest.json 中：
    backend.metadata.visibility = "private"
    backend.metadata.required_permission 非空
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(plugin_dir: Path) -> dict:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("缺少 manifest.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = (data.get("backend") or {}).get("metadata") or {}
    if metadata.get("visibility") != "private":
        raise SystemExit("私有包必须在 backend.metadata.visibility 声明 private")
    if not metadata.get("required_permission"):
        raise SystemExit("私有包必须声明 backend.metadata.required_permission")
    if not data.get("id") or not data.get("name"):
        raise SystemExit("manifest.json 缺少 id 或 name")
    return data


def iter_files(plugin_dir: Path):
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    plugin_dir = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    if not plugin_dir.is_dir():
        raise SystemExit(f"目录不存在: {plugin_dir}")

    manifest = validate_manifest(plugin_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in iter_files(plugin_dir):
            zf.write(path, path.relative_to(plugin_dir).as_posix())

    print(
        json.dumps(
            {
                "plugin_id": manifest["id"],
                "version": manifest.get("version", ""),
                "zip": str(output),
                "size": output.stat().st_size,
                "sha256": sha256(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
