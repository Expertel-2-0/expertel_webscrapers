"""
Search ScraperJobs by filters (carrier, type, status, date range) — distinct from analyze_jobs.py
which takes explicit IDs.

Examples:
    poetry run python scripts/db_analysis/find_jobs.py --carrier Bell --type daily_usage --since 2026-05-15
    poetry run python scripts/db_analysis/find_jobs.py --carrier Bell --type daily_usage --since 2026-05-01 --status completed
    poetry run python scripts/db_analysis/find_jobs.py --carrier Bell --since 2026-05-15 --group-by status,type
"""

import argparse
import io
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from web_scrapers.infrastructure.django.models import ScraperJob  # noqa: E402


def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def hr(c="=", w=120):
    return c * w


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--carrier", help="Filter by carrier name (icontains)")
    p.add_argument("--type", help="Filter by ScraperJob.type (exact, e.g. daily_usage, monthly_reports, pdf_invoice)")
    p.add_argument("--status", help="Filter by ScraperJob.status (exact, e.g. completed, error, pending)")
    p.add_argument("--since", help="Only jobs whose billing_cycle.end_date >= this date (YYYY-MM-DD)")
    p.add_argument("--until", help="Only jobs whose billing_cycle.start_date <= this date (YYYY-MM-DD)")
    p.add_argument("--bc-open-only", action="store_true", help="Only billing cycles with status='open'")
    p.add_argument(
        "--group-by",
        default="status",
        help="Comma list of fields to group counts by (status,type,carrier,client)",
    )
    p.add_argument("--list", action="store_true", help="Print every matching job (default off)")
    p.add_argument("--limit-list", type=int, default=200, help="Cap rows when --list")
    args = p.parse_args()

    qs = ScraperJob.objects.select_related(
        "billing_cycle__account__workspace__client",
        "billing_cycle__account__carrier",
    )

    if args.carrier:
        qs = qs.filter(billing_cycle__account__carrier__name__icontains=args.carrier)
    if args.type:
        qs = qs.filter(type=args.type)
    if args.status:
        qs = qs.filter(status=args.status)
    if args.since:
        qs = qs.filter(billing_cycle__end_date__gte=parse_date(args.since))
    if args.until:
        qs = qs.filter(billing_cycle__start_date__lte=parse_date(args.until))
    if args.bc_open_only:
        qs = qs.filter(billing_cycle__status="open")

    total = qs.count()
    print(
        f"DB={os.environ.get('DB_NAME','?')}  filters: "
        f"carrier={args.carrier} type={args.type} status={args.status} "
        f"since={args.since} until={args.until} bc_open_only={args.bc_open_only}"
    )
    print(f"Total matches: {total}\n")
    if total == 0:
        return

    # Grouping
    fields = [f.strip() for f in args.group_by.split(",") if f.strip()]
    valid = {"status", "type", "carrier", "client"}
    bad = [f for f in fields if f not in valid]
    if bad:
        raise SystemExit(f"Invalid --group-by fields: {bad}. Valid: {sorted(valid)}")

    print(hr())
    print(f"GROUPED BY {fields}")
    print(hr())

    counts = defaultdict(int)
    accounts_per_group = defaultdict(set)
    for j in qs.iterator():
        carrier = j.billing_cycle.account.carrier.name
        client = j.billing_cycle.account.workspace.client.name
        key = tuple(
            {"status": j.status, "type": j.type, "carrier": carrier, "client": client}[f] for f in fields
        )
        counts[key] += 1
        accounts_per_group[key].add(j.billing_cycle.account.number)

    header = "  " + "  ".join(f"{f:<20}" for f in fields) + f"  {'jobs':>6}  {'accts':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for key, c in sorted(counts.items(), key=lambda x: -x[1]):
        cells = "  ".join(f"{str(v)[:19]:<20}" for v in key)
        print(f"  {cells}  {c:>6}  {len(accounts_per_group[key]):>6}")

    if args.list:
        print(f"\n{hr()}\nDETAIL (limit {args.limit_list})\n{hr()}")
        print(
            f"  {'JobID':<7}{'Status':<12}{'Type':<14}{'Carrier':<10}"
            f"{'Account#':<13}{'Client':<25}{'BC_ID':<7}{'BC_Period':<24}{'Retry'}"
        )
        for j in qs.order_by("id")[: args.limit_list]:
            bc = j.billing_cycle
            acc = bc.account
            client = acc.workspace.client.name[:24]
            carrier = acc.carrier.name[:9]
            print(
                f"  {j.id:<7}{j.status:<12}{j.type:<14}{carrier:<10}"
                f"{acc.number:<13}{client:<25}{bc.id:<7}{bc.start_date}->{bc.end_date}  "
                f"{j.retry_count}/{j.max_retries}"
            )


if __name__ == "__main__":
    main()
