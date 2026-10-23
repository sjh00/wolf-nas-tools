"""P2-2 媒体身份回填脚本.

用法：
    uv run python scripts/backfill_media_identity.py            # 只读试跑
    uv run python scripts/backfill_media_identity.py --apply    # 实际写入
    uv run python scripts/backfill_media_identity.py --limit 500 --apply
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.services.metadata_backfill_service import MetadataBackfillService


def main() -> int:
    parser = argparse.ArgumentParser(description="回填旧 TMDBID/DB:/BG: 到媒体身份表")
    parser.add_argument("--apply", action="store_true", help="实际写库；默认 dry-run")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少行")
    args = parser.parse_args()

    report = MetadataBackfillService().run(dry_run=not args.apply, limit=args.limit)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
