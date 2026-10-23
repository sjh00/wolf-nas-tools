"""ADR-025 之前历史数据的多元数据锚点迁移脚本.

源数据：ADR-025 之前的 SUBSCRIBE_*/DOWNLOAD_HISTORY/TRANSFER_HISTORY/LIBRARY_MEDIA_METADATA，
兼容 TMDB 数字 ID、DB:<id>、BG:<id>。
目标：ANCHOR_PROVIDER / ANCHOR_EXTERNAL_ID / IDENTITY_ID / CONTENT_PROFILE。

必须在 schema 升级后运行：
    uv run alembic upgrade head

用法：
    uv run python scripts/migrate_multisource_refs.py            # dry-run
    uv run python scripts/migrate_multisource_refs.py --apply    # 写库
    uv run python scripts/migrate_multisource_refs.py --apply --limit 500
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.services.multisource_migration_service import MultiSourceMigrationService


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移旧 TMDBID/DB:/BG: 到 ANCHOR_* + IDENTITY_ID")
    parser.add_argument("--apply", action="store_true", help="实际写库；默认 dry-run")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少行")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="容器启动用：完成过本版本迁移则直接跳过",
    )
    parser.add_argument("--marker", default=None, help="完成标记路径（默认 data/.migrations）")
    args = parser.parse_args()

    marker_path = (
        Path(args.marker)
        if args.marker
        else Path(os.environ.get("NEXUS_MEDIA_DATA") or "data") / ".migrations" / "multisource_refs_v1.done"
    )
    if args.auto and marker_path.exists():
        print(json.dumps({"skipped": True, "marker": str(marker_path)}, ensure_ascii=False, indent=2))
        return 0

    report = MultiSourceMigrationService().run(dry_run=not args.apply, limit=args.limit)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if args.apply and not report.errors:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("done\n", encoding="utf-8")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
