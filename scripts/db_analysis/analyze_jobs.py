"""
Inspect a set of ScraperJob IDs against the live DB.

Reusable across carriers / failure categories. Pass IDs via --ids, --ids-file, or stdin.

Examples:
    poetry run python scripts/db_analysis/analyze_jobs.py --label "Bell 2FA" --ids 728,729,751,752
    poetry run python scripts/db_analysis/analyze_jobs.py --label "Telus CF" --ids-file telus_ids.txt
    echo "1,2,3" | poetry run python scripts/db_analysis/analyze_jobs.py --label "ad-hoc"
"""

import argparse
import io
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from web_scrapers.infrastructure.django.models import ScraperJob  # noqa: E402


def parse_ids(raw: str):
    return sorted({int(x) for x in re.split(r"[,\s]+", raw.strip()) if x})


def load_ids(args):
    if args.ids:
        return parse_ids(args.ids)
    if args.ids_file:
        return parse_ids(Path(args.ids_file).read_text())
    if not sys.stdin.isatty():
        return parse_ids(sys.stdin.read())
    raise SystemExit("Provide --ids, --ids-file, or pipe IDs via stdin")


def hr(char="=", width=110):
    return char * width


def section(title, char="="):
    print(f"\n{hr(char)}\n{title}\n{hr(char)}")


def main():
    parser = argparse.ArgumentParser(description="Inspect ScraperJob IDs against the DB.")
    parser.add_argument("--ids", help="Comma/space-separated job IDs")
    parser.add_argument("--ids-file", help="Path to a file containing job IDs")
    parser.add_argument("--label", default="jobs", help="Label for this batch (e.g. 'Bell 2FA')")
    parser.add_argument(
        "--show-log-tail",
        type=int,
        default=0,
        help="Show last N chars of each job's log column (0 = off)",
    )
    parser.add_argument(
        "--per-account-log",
        type=int,
        default=0,
        help="For each unique account, show last N chars of the most recent job's log (0 = off)",
    )
    parser.add_argument(
        "--log-grep",
        default="",
        help="When showing logs, only print lines matching this regex (case-insensitive)",
    )
    parser.add_argument(
        "--tabular",
        action="store_true",
        help="Print ONLY a compact detail table (no per-client / per-account / summary sections)",
    )
    parser.add_argument(
        "--error-label",
        default="",
        help="Free-text label appended as an 'Error' column when --tabular is used",
    )
    parser.add_argument(
        "--carrier-filter",
        help="Only include jobs whose account.carrier.name matches this (case-insensitive substring)",
    )
    args = parser.parse_args()

    ids = load_ids(args)
    print(f"[{args.label}] querying {len(ids)} job IDs from DB ({os.environ.get('DB_NAME', '?')})\n")

    jobs_qs = (
        ScraperJob.objects.filter(id__in=ids)
        .select_related(
            "billing_cycle__account__workspace__client",
            "billing_cycle__account__carrier",
            "scraper_config__credential",
        )
        .order_by("billing_cycle__account__carrier__name", "billing_cycle__account__workspace__client__name", "id")
    )

    if args.carrier_filter:
        jobs_qs = jobs_qs.filter(billing_cycle__account__carrier__name__icontains=args.carrier_filter)

    jobs = list(jobs_qs)
    found_ids = {j.id for j in jobs}
    missing = sorted(set(ids) - found_ids)
    if missing:
        print(f"WARNING: {len(missing)} job IDs not found in DB: {missing}\n")
    print(f"Loaded {len(jobs)} jobs.\n")

    if not jobs:
        return

    # ---- per-job detail ----
    if args.tabular:
        # Compact, single-table layout with ids + optional error label
        print(f"\n=== {args.label}  ({len(jobs)} jobs)  error={args.error_label or '(see logs)'} ===")
        print(
            f"{'JobID':<7}{'Type':<14}{'ClientID':<9}{'Client':<30}"
            f"{'AcctID':<7}{'Acct#':<13}{'BC_ID':<7}{'BC_Period':<24}{'Status':<8}{'Retry':<6}{'Error'}"
        )
        print(hr("-", 160))
    else:
        section(f"DETAIL — {args.label}")
        print(
            f"{'JobID':<7}{'Carrier':<10}{'Status':<13}{'Type':<14}"
            f"{'Account#':<13}{'Client':<22}"
            f"{'BC_ID':<7}{'BC_Period':<24}{'BC_Status':<10}{'Retry'}"
        )
        print(hr("-", 140))

    by_client = defaultdict(list)
    by_account = defaultdict(list)
    by_credential = defaultdict(list)
    by_carrier = defaultdict(list)
    by_status = defaultdict(int)
    by_type = defaultdict(int)
    by_billing_cycle = defaultdict(list)

    for j in jobs:
        bc = j.billing_cycle
        acc = bc.account
        cli = acc.workspace.client
        carrier = acc.carrier.name
        cred = j.scraper_config.credential if j.scraper_config_id else None

        client_name = cli.name[:21]
        bc_period = f"{bc.start_date} -> {bc.end_date}"
        if args.tabular:
            print(
                f"{j.id:<7}{j.type:<14}{cli.id:<9}{cli.name[:29]:<30}"
                f"{acc.id:<7}{acc.number:<13}{bc.id:<7}{bc_period:<24}"
                f"{j.status:<8}{j.retry_count}/{j.max_retries:<4}{args.error_label}"
            )
        else:
            print(
                f"{j.id:<7}{carrier[:9]:<10}{j.status:<13}{j.type:<14}"
                f"{acc.number:<13}{client_name:<22}"
                f"{bc.id:<7}{bc_period:<24}{bc.status:<10}{j.retry_count}/{j.max_retries}"
            )

        by_client[cli.name].append(j)
        by_account[(carrier, acc.number)].append(j)
        by_carrier[carrier].append(j)
        by_status[j.status] += 1
        by_type[j.type] += 1
        by_billing_cycle[bc.id].append(j)
        if cred:
            by_credential[(cred.id, cred.username, cli.name)].append(j)

    def filtered_log(text: str, max_chars: int) -> str:
        text = text or ""
        if args.log_grep:
            pat = re.compile(args.log_grep, re.IGNORECASE)
            text = "\n".join(line for line in text.splitlines() if pat.search(line))
        if max_chars and len(text) > max_chars:
            text = text[-max_chars:]
        return text

    if args.tabular:
        return

    if args.show_log_tail > 0:
        section("LOG TAIL")
        for j in jobs:
            tail = filtered_log(j.log or "", args.show_log_tail).replace("\n", "\n      ")
            print(f"\n  Job {j.id}:\n      {tail}")

    if args.per_account_log > 0:
        section("LOG BY ACCOUNT (most recent job per account)")
        for (carrier, acc_num), jl in sorted(by_account.items()):
            latest = max(jl, key=lambda j: j.id)
            first = latest.billing_cycle.account
            client = first.workspace.client.name
            bc = latest.billing_cycle
            text = filtered_log(latest.log or "", args.per_account_log)
            print(
                f"\n--- [{carrier}] account={acc_num} client={client} "
                f"bc={bc.id} ({bc.start_date}->{bc.end_date}) | "
                f"latest job={latest.id} status={latest.status} retry={latest.retry_count}/{latest.max_retries}"
            )
            if not text:
                print("    (empty log or no matches for grep)")
            else:
                for line in text.splitlines():
                    print(f"    {line}")

    # ---- by carrier ----
    if len(by_carrier) > 1:
        section("BY CARRIER")
        for carrier, jl in sorted(by_carrier.items(), key=lambda x: -len(x[1])):
            print(f"  {carrier:<20} jobs={len(jl)}")

    # ---- by client ----
    section("BY CLIENT")
    for client, jl in sorted(by_client.items(), key=lambda x: -len(x[1])):
        accounts = {j.billing_cycle.account.number for j in jl}
        statuses = defaultdict(int)
        for j in jl:
            statuses[j.status] += 1
        status_str = ", ".join(f"{s}:{c}" for s, c in sorted(statuses.items()))
        print(f"  {client:<35} jobs={len(jl):<3} accounts={len(accounts):<3} [{status_str}]")

    # ---- by account ----
    section("BY ACCOUNT")
    for (carrier, acc_num), jl in sorted(by_account.items(), key=lambda x: -len(x[1])):
        first = jl[0].billing_cycle.account
        client = first.workspace.client.name
        nick = first.nickname or ""
        types = sorted({j.type for j in jl})
        statuses = sorted({j.status for j in jl})
        retries = {j.retry_count for j in jl}
        bc_ids = sorted({j.billing_cycle.id for j in jl})
        bc_periods = sorted({f"{j.billing_cycle.start_date}->{j.billing_cycle.end_date}" for j in jl})
        print(
            f"  [{carrier[:8]:<8}] {acc_num:<14} {nick[:30]:<32} "
            f"client={client[:22]:<22} jobs={len(jl)} types={types} status={statuses} retry={retries}"
        )
        print(f"      billing_cycles={bc_ids} periods={bc_periods}")

    # ---- by billing cycle ----
    section("BY BILLING CYCLE")
    for bc_id, jl in sorted(by_billing_cycle.items(), key=lambda x: -len(x[1])):
        bc = jl[0].billing_cycle
        acc = bc.account
        client = acc.workspace.client.name
        carrier = acc.carrier.name
        types = sorted({j.type for j in jl})
        statuses = sorted({j.status for j in jl})
        print(
            f"  bc_id={bc_id:<6} [{carrier[:8]:<8}] acct={acc.number:<13} "
            f"client={client[:22]:<22} period={bc.start_date}->{bc.end_date} "
            f"bc_status={bc.status:<10} jobs={len(jl)} types={types} job_status={statuses}"
        )

    # ---- by credential ----
    section("BY PORTAL CREDENTIAL")
    for (cred_id, username, client), jl in sorted(by_credential.items(), key=lambda x: -len(x[1])):
        accounts = {j.billing_cycle.account.number for j in jl}
        print(
            f"  cred_id={cred_id:<5} user={username[:35]:<35} "
            f"client={client[:25]:<25} accounts={len(accounts)} jobs={len(jl)}"
        )

    # ---- summary ----
    section(f"SUMMARY — {args.label}")
    print(f"  Total IDs requested:  {len(ids)}")
    print(f"  Found in DB:          {len(jobs)}")
    if missing:
        print(f"  Missing:              {len(missing)} -> {missing}")
    print(f"  Carriers:             {dict((c, len(jl)) for c, jl in by_carrier.items())}")
    print(f"  Clients:              {len(by_client)}")
    print(f"  Accounts:             {len(by_account)}")
    print(f"  Billing cycles:       {len(by_billing_cycle)}")
    print(f"  Credentials:          {len(by_credential)}")
    print(f"  Current job status:   {dict(by_status)}")
    print(f"  Job types:            {dict(by_type)}")


if __name__ == "__main__":
    main()
