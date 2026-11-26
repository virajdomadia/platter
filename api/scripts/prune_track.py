"""Delete rider trails (`rider_track`) of orders closed more than 7 days ago (05 §7: positions are
kept only as long as they are useful to the customer and the case study).

    PRUNE_DATABASE_URL=… uv run python -m scripts.prune_track [--days 7] [--dry-run]

Like migrations and the seed, it never reads DATABASE_URL — name the target explicitly.
"""

import argparse
import asyncio
import os
import sys

from sqlalchemy import text

from app.core.db import make_engine

SQL = """
{verb} rider_track t
using orders o
where o.id = t.order_id
  and o.status in ('delivered', 'rejected', 'cancelled', 'expired')
  and coalesce(o.delivered_at, o.rejected_at, o.cancelled_at, o.expired_at)
      < now() - make_interval(days => :days)
"""


async def run(url: str, days: int, dry_run: bool) -> int:
    engine = make_engine(url)
    async with engine.begin() as conn:
        if dry_run:
            count_sql = SQL.format(verb="select count(*) from").replace(
                "using orders o", ", orders o"
            )
            n = (await conn.execute(text(count_sql), {"days": days})).scalar_one()
        else:
            n = (await conn.execute(text(SQL.format(verb="delete from")), {"days": days})).rowcount
    await engine.dispose()
    return int(n or 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=os.environ.get("PRUNE_DATABASE_URL"))
    parser.add_argument("--days", type=int, default=7)
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
