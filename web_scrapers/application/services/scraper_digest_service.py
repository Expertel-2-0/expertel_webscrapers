"""
Application-layer service that builds the daily scraper health digest.

All database access uses the Django ORM — no raw SQL.  Each public method
includes a docstring that references the corresponding query in
``scraper_health_diagnostic.sql`` (Q1–Q6) at the repository root.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from django.conf import settings
from django.db.models import (
    Avg,
    Count,
    F,
    Func,
    Max,
    Q,
    TextField,
    Value,
)
from django.utils import timezone

from web_scrapers.domain.digest import (
    CellErrorSummary,
    CellHealth,
    DigestData,
    ErrorJobDetail,
    ErrorPriority,
    RunRate,
    SilentGap,
    ZombieJob,
    classify_error_log,
    job_type_label,
)
from web_scrapers.infrastructure.django.enums import (
    FileStatusChoices,
    ScraperJobStatus,
    ScraperType,
)
from web_scrapers.infrastructure.django.models import ScraperJob

logger = logging.getLogger(__name__)


class ScraperDigestService:
    """
    Builds the DigestData payload used by ScraperDailyDigestMailable.

    All queries use the Django ORM against the shared PostgreSQL database.
    The ``now`` constructor parameter allows injecting a fixed timestamp for
    testing without touching the database.

    Query references (scraper_health_diagnostic.sql):
        Q1  — 18-cell health matrix (carrier × type)
        Q3  — zombie jobs (stuck in_progress / running)
        Q4  — file-level reconciliation (silent gaps)
        Q5  — most recent error log per failing cell
        Q6  — run-rate sanity check (jobs per day)
    """

    ZOMBIE_THRESHOLD_HOURS: int = 6
    _HEALTH_WINDOW_DAYS: int = 7
    _ERROR_WINDOW_HOURS: int = 24
    _SILENT_GAP_WINDOW_HOURS: int = 24

    def __init__(self, now: Optional[datetime] = None) -> None:
        """
        Parameters
        ----------
        now:
            Reference timestamp for all relative time calculations.
            Defaults to ``timezone.now()`` when omitted.
        """
        self._now: datetime = now or timezone.now()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_digest(self) -> DigestData:
        """
        Assemble the complete DigestData payload for the daily digest email.

        Calls all sub-queries, aggregates global counters, and computes the
        global 24-hour success percentage.

        Returns
        -------
        DigestData
        """
        window_end = self._now
        window_start = window_end - timedelta(hours=self._ERROR_WINDOW_HOURS)
        zombie_threshold = window_end - timedelta(hours=self.ZOMBIE_THRESHOLD_HOURS)

        errors_by_cell = self.get_errors_by_cell(since=window_start)
        health_context = self.get_health_context(since=window_end - timedelta(days=self._HEALTH_WINDOW_DAYS))
        zombies = self.get_zombie_jobs(threshold=zombie_threshold)
        silent_gaps = self.get_silent_gaps(since=window_start)
        run_rate = self.get_run_rate()

        error_count = sum(c.error_count for c in errors_by_cell)
        high_error_count = sum(c.high_count for c in errors_by_cell)
        low_error_count = sum(c.low_count for c in errors_by_cell)
        zombie_count = len(zombies)

        # Global 24h success percentage
        global_counts = ScraperJob.objects.filter(
            completed_at__gte=window_start,
            status__in=[ScraperJobStatus.SUCCESS, ScraperJobStatus.ERROR],
        ).aggregate(
            success=Count("id", filter=Q(status=ScraperJobStatus.SUCCESS)),
            total=Count("id"),
        )
        total_24h = global_counts["total"] or 0
        success_24h = global_counts["success"] or 0
        success_pct: Optional[float] = round(100.0 * success_24h / total_24h, 1) if total_24h > 0 else None

        alerts_url = f"{settings.FRONTEND_URL}/scraper-jobs"

        return DigestData(
            report_date=self._now.date(),
            window_start=window_start,
            window_end=window_end,
            errors_by_cell=errors_by_cell,
            health_context=health_context,
            zombies=zombies,
            silent_gaps=silent_gaps,
            run_rate=run_rate,
            error_count=error_count,
            high_error_count=high_error_count,
            low_error_count=low_error_count,
            zombie_count=zombie_count,
            success_pct=success_pct,
            alerts_url=alerts_url,
        )

    def get_errors_by_cell(self, since: datetime) -> list[CellErrorSummary]:
        """
        Return one CellErrorSummary per (carrier, job_type) with errors in the
        24-hour window, ordered HIGH cells first then by error_count desc.

        Corresponds to Q1 + Q5 in scraper_health_diagnostic.sql.

        Each job's log tail (last 500 chars) is fetched via the PostgreSQL
        ``RIGHT()`` function and classified with ``classify_error_log()``.
        Aggregation is done in Python to enable per-job priority tracking.

        Parameters
        ----------
        since:
            Lower bound for ``completed_at`` (exclusive).

        Returns
        -------
        list[CellErrorSummary]
            Sorted: HIGH priority cells first, then by error_count descending.
        """
        qs = (
            ScraperJob.objects.filter(
                status=ScraperJobStatus.ERROR,
                completed_at__gte=since,
            )
            .annotate(
                carrier_name=F("scraper_config__carrier__name"),
                account_id=F("scraper_config__account_id"),
                client_id=F("scraper_config__account__workspace__client_id"),
                log_tail=Func(
                    F("log"),
                    Value(500),
                    function="RIGHT",
                    output_field=TextField(),
                ),
            )
            .values(
                "id",
                "carrier_name",
                "type",
                "account_id",
                "client_id",
                "completed_at",
                "log_tail",
            )
            .order_by("carrier_name", "type", "-completed_at")
        )

        # Group in Python
        from collections import defaultdict

        cells: dict[tuple[str, str], dict] = defaultdict(
            lambda: {
                "jobs": [],
                "account_ids": set(),
                "client_ids": set(),
                "last_error_at": None,
            }
        )

        for row in qs:
            key = (row["carrier_name"], row["type"])
            priority = classify_error_log(row["log_tail"])
            cells[key]["jobs"].append(
                ErrorJobDetail(
                    job_id=row["id"],
                    priority=priority,
                    completed_at=row["completed_at"],
                    log_tail=row["log_tail"],
                )
            )
            if row["account_id"]:
                cells[key]["account_ids"].add(row["account_id"])
            if row["client_id"]:
                cells[key]["client_ids"].add(row["client_id"])
            if row["completed_at"] and (
                cells[key]["last_error_at"] is None or row["completed_at"] > cells[key]["last_error_at"]
            ):
                cells[key]["last_error_at"] = row["completed_at"]

        summaries: list[CellErrorSummary] = []
        for (carrier, jtype), data in cells.items():
            jobs: list[ErrorJobDetail] = data["jobs"]
            high_count = sum(1 for j in jobs if j.priority == ErrorPriority.HIGH)
            low_count = len(jobs) - high_count
            summaries.append(
                CellErrorSummary(
                    carrier=carrier,
                    job_type=jtype,
                    job_type_label=job_type_label(jtype),
                    error_count=len(jobs),
                    high_count=high_count,
                    low_count=low_count,
                    priority=ErrorPriority.HIGH if high_count > 0 else ErrorPriority.LOW,
                    accounts_affected=len(data["account_ids"]),
                    clients_affected=len(data["client_ids"]),
                    jobs=jobs,
                    last_error_at=data["last_error_at"],
                )
            )

        # HIGH cells first, then by error_count desc
        summaries.sort(key=lambda c: (0 if c.priority == ErrorPriority.HIGH else 1, -c.error_count))
        return summaries

    def get_health_context(self, since: datetime) -> list[CellHealth]:
        """
        Return one CellHealth row per (carrier, job_type) for all jobs in the
        rolling 7-day window.  Aggregation uses ORM annotations; success_pct
        is computed in Python (None when denominator is 0).

        Corresponds to Q1 in scraper_health_diagnostic.sql (7-day window).

        Parameters
        ----------
        since:
            Lower bound for ``completed_at`` (exclusive).

        Returns
        -------
        list[CellHealth]
            Sorted: success_pct ascending, rows with None success_pct last.
        """
        qs = (
            ScraperJob.objects.filter(
                completed_at__gte=since,
                status__in=[ScraperJobStatus.SUCCESS, ScraperJobStatus.ERROR],
            )
            .annotate(carrier_name=F("scraper_config__carrier__name"))
            .values("carrier_name", "type")
            .annotate(
                success=Count("id", filter=Q(status=ScraperJobStatus.SUCCESS)),
                error=Count("id", filter=Q(status=ScraperJobStatus.ERROR)),
                succeeded_after_retry=Count(
                    "id",
                    filter=Q(status=ScraperJobStatus.SUCCESS, retry_count__gt=0),
                ),
                avg_retries_on_success=Avg("retry_count", filter=Q(status=ScraperJobStatus.SUCCESS)),
                last_success=Max("completed_at", filter=Q(status=ScraperJobStatus.SUCCESS)),
                last_error=Max("completed_at", filter=Q(status=ScraperJobStatus.ERROR)),
            )
        )

        results: list[CellHealth] = []
        for row in qs:
            denominator = (row["success"] or 0) + (row["error"] or 0)
            success_pct: Optional[float] = (
                round(100.0 * (row["success"] or 0) / denominator, 1) if denominator > 0 else None
            )
            avg_retries: Optional[float] = (
                round(float(row["avg_retries_on_success"]), 2) if row["avg_retries_on_success"] is not None else None
            )
            results.append(
                CellHealth(
                    carrier=row["carrier_name"],
                    job_type=row["type"],
                    job_type_label=job_type_label(row["type"]),
                    success=row["success"] or 0,
                    error=row["error"] or 0,
                    success_pct=success_pct,
                    succeeded_after_retry=row["succeeded_after_retry"] or 0,
                    avg_retries_on_success=avg_retries,
                    last_success=row["last_success"],
                    last_error=row["last_error"],
                )
            )

        # Sort: success_pct asc, None last
        results.sort(key=lambda c: (c.success_pct is None, c.success_pct or 0.0))
        return results

    def get_zombie_jobs(self, threshold: datetime) -> list[ZombieJob]:
        """
        Return jobs stuck in ``in_progress`` or ``running`` state.

        A job is considered a zombie when ``available_at`` is earlier than
        ``threshold`` (6 hours ago by default) OR when ``available_at`` is
        NULL.  NULL is included intentionally: a job with no scheduled time
        that is still running has no reasonable explanation.

        Corresponds to Q3 in scraper_health_diagnostic.sql.

        Parameters
        ----------
        threshold:
            Jobs with ``available_at < threshold`` are considered zombies.
            Jobs with ``available_at IS NULL`` are always included.

        Returns
        -------
        list[ZombieJob]
            Sorted: available_at ascending, NULL first.
        """
        qs = (
            ScraperJob.objects.filter(
                status__in=[ScraperJobStatus.IN_PROGRESS, ScraperJobStatus.RUNNING],
            )
            .filter(Q(available_at__lt=threshold) | Q(available_at__isnull=True))
            .select_related(
                "scraper_config__carrier",
                "scraper_config__account",
            )
            .order_by(F("available_at").asc(nulls_first=True))
        )

        return [
            ZombieJob(
                job_id=job.id,
                carrier=job.scraper_config.carrier.name,
                job_type=job.type,
                job_type_label=job_type_label(job.type),
                status=job.status,
                account_number=job.scraper_config.account.number,
                retry_count=job.retry_count,
                available_at=job.available_at,
            )
            for job in qs
        ]

    def get_silent_gaps(self, since: datetime) -> list[SilentGap]:
        """
        Return monthly-reports jobs that succeeded but whose billing cycle
        still has unprocessed files.

        Corresponds to Q4 in scraper_health_diagnostic.sql.

        A job is flagged as a silent gap when:
        - ``type = monthly_reports``
        - ``status = success``
        - ``completed_at >= since``
        - at least one associated BillingCycleFile has a status other than
          ``processed``

        The related_name on BillingCycleFile.billing_cycle is
        ``billing_cycle_files`` (as defined in models.py).

        Parameters
        ----------
        since:
            Lower bound for ``completed_at``.

        Returns
        -------
        list[SilentGap]
            Sorted: not_processed descending.
        """
        qs = (
            ScraperJob.objects.filter(
                type=ScraperType.MONTHLY_REPORTS,
                status=ScraperJobStatus.SUCCESS,
                completed_at__gte=since,
            )
            .annotate(
                carrier_name=F("scraper_config__carrier__name"),
                account_number_val=F("scraper_config__account__number"),
                total_files=Count("billing_cycle__billing_cycle_files"),
                processed=Count(
                    "billing_cycle__billing_cycle_files",
                    filter=Q(billing_cycle__billing_cycle_files__status=FileStatusChoices.PROCESSED),
                ),
                error_files=Count(
                    "billing_cycle__billing_cycle_files",
                    filter=Q(billing_cycle__billing_cycle_files__status=FileStatusChoices.ERROR),
                ),
                still_to_fetch=Count(
                    "billing_cycle__billing_cycle_files",
                    filter=Q(billing_cycle__billing_cycle_files__status=FileStatusChoices.TO_BE_FETCHED),
                ),
                not_processed=Count(
                    "billing_cycle__billing_cycle_files",
                    filter=~Q(billing_cycle__billing_cycle_files__status=FileStatusChoices.PROCESSED),
                ),
            )
            .filter(total_files__gt=0, not_processed__gt=0)
            .order_by("-not_processed")
        )

        return [
            SilentGap(
                job_id=row.id,
                carrier=row.carrier_name,
                account_number=row.account_number_val,
                billing_cycle_id=row.billing_cycle_id,
                completed_at=row.completed_at,
                total_files=row.total_files,
                processed=row.processed,
                error_files=row.error_files,
                still_to_fetch=row.still_to_fetch,
                not_processed=row.not_processed,
            )
            for row in qs
        ]

    def get_run_rate(self) -> RunRate:
        """
        Compare yesterday's finished-job count against the trailing 7-day average.

        Corresponds to Q6 in scraper_health_diagnostic.sql.

        ``yesterday`` is the full calendar day (UTC) immediately preceding
        ``self._now``.  The trailing baseline is the mean daily count over the
        7 days before yesterday, giving a stable reference that excludes
        yesterday itself.

        ``flagged`` is True when the baseline is positive and yesterday's
        finished count is less than 50 % of the baseline — a signal of a
        potential scheduler or processor outage.

        Returns
        -------
        RunRate
        """
        today_start = self._now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        baseline_start = yesterday_start - timedelta(days=7)

        # Yesterday's counts
        yesterday_agg = ScraperJob.objects.filter(
            completed_at__gte=yesterday_start,
            completed_at__lt=today_start,
            status__in=[ScraperJobStatus.SUCCESS, ScraperJobStatus.ERROR],
        ).aggregate(
            finished=Count("id"),
            success=Count("id", filter=Q(status=ScraperJobStatus.SUCCESS)),
            error=Count("id", filter=Q(status=ScraperJobStatus.ERROR)),
        )

        yesterday_finished: int = yesterday_agg["finished"] or 0
        yesterday_success: int = yesterday_agg["success"] or 0
        yesterday_error: int = yesterday_agg["error"] or 0

        # Trailing 7-day total (7 full days before yesterday)
        trailing_total = ScraperJob.objects.filter(
            completed_at__gte=baseline_start,
            completed_at__lt=yesterday_start,
            status__in=[ScraperJobStatus.SUCCESS, ScraperJobStatus.ERROR],
        ).count()
        trailing_avg = trailing_total / 7.0

        flagged = trailing_avg > 0 and yesterday_finished < 0.5 * trailing_avg

        return RunRate(
            yesterday=yesterday_start.date(),
            yesterday_finished=yesterday_finished,
            yesterday_success=yesterday_success,
            yesterday_error=yesterday_error,
            trailing_7d_avg=round(trailing_avg, 1),
            flagged=flagged,
        )
