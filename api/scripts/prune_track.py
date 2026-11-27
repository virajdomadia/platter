"""Run the retention prune by hand (`dispatch.prune`; it also runs lazily on every demo login):
a real rider's stale fix, rider trails of orders closed more than 7 days ago, spent rate limits.

    PRUNE_DATABASE_URL=… uv run python -m scripts.prune_track [--days 7] [--dry-run]

Like migrations and the seed, it never reads DATABASE_URL — name the target explicitly.
"""

import argparse
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.db import make_engine
from app.services import dispatch


async def run(url: str, days: int, dry_run: bool) -> int:
    engine = make_engine(url)
    async with async_sessionmaker(engine)() as db:
        n = await dispatch.prune(db, days)
        await (db.rollback() if dry_run else db.commit())
    await engine.dispose()
    return n


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=os.environ.get("PRUNE_DATABASE_URL"))
    parser.add_argument("--days", type=int, default=dispatch.TRAIL_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        print("Set PRUNE_DATABASE_URL or pass --database-url.", file=sys.stderr)
        return 2
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    n = asyncio.run(run(args.database_url, args.days, args.dry_run))
    verb = "would delete" if args.dry_run else "deleted"
    print(f"{verb} {n} track points older than {args.days} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
