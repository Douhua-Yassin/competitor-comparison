from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import AuditConfigurationError, AuditSettings
from .runner import AuditRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="领星 OpenAPI 第一阶段只读接口盘点")
    parser.add_argument("--env", type=Path, help="指定 .env 路径，默认使用项目根目录 .env")
    parser.add_argument("--json", action="store_true", help="在控制台输出完整 JSON")
    return parser


async def _main() -> int:
    args = build_parser().parse_args()
    try:
        settings = AuditSettings.load(args.env)
    except AuditConfigurationError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    print("开始领星 OpenAPI 只读接口盘点……")
    print(json.dumps(settings.public_summary(), ensure_ascii=False, indent=2))
    report = await AuditRunner(settings).run()
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n盘点完成：")
        for status, count in sorted(report.summary.items()):
            print(f"  {status}: {count}")
        print(f"报告目录：{settings.output_dir / report.run_id}")
    return 0 if report.summary.get("success", 0) > 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
