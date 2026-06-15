"""
Domain entities for the daily scraper health digest.

This module defines the pure data structures used to represent the daily
scraper health report.  Nothing here touches the database or sends email —
those concerns belong to the application and infrastructure layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Error priority classification
# ---------------------------------------------------------------------------

# Low-priority keywords (case-insensitive).  A log whose tail matches any of
# these phrases indicates a *credential / access* problem that the operations
# team can fix by updating login details — no code change needed.
_LOW_PRIORITY_PATTERNS: tuple[str, ...] = (
    "login failed",
    "invalid credentials",
    "credentials",
    "2fa",
    "mfa",
    "captcha",
    "password",
    "sign in",
    "sign-in",
    "authentication",
)


class ErrorPriority(str, Enum):
    """
    Priority classification for a scraper error job.

    HIGH  — requires developer intervention: broken selectors, download
            failures, ZIP extraction errors, upload errors, timeouts, or any
            error that cannot be resolved by simply updating credentials.

    LOW   — resolvable by updating carrier portal credentials without any
            code change (login failures, invalid passwords, 2FA/MFA/CAPTCHA
            challenges, etc.).
    """

    HIGH = "high"
    LOW = "low"


def classify_error_log(log_tail: str | None) -> ErrorPriority:
    """
    Classify a scraper error by examining the tail of its log.

    Rule
    ----
    Return LOW if *log_tail* (case-insensitive) contains any of the
    credential/access-related keywords defined in _LOW_PRIORITY_PATTERNS,
    because those errors can be fixed by updating credentials without code
    changes.  Return HIGH for everything else — including empty / None log
    tails — because they require developer investigation (broken selectors,
    download failures, ZIP/upload errors, timeouts, unknown failures).

    Parameters
    ----------
    log_tail:
        The last N characters of a scraper job log, or None if no log exists.

    Returns
    -------
    ErrorPriority.LOW  if the log tail matches a credential/access pattern.
    ErrorPriority.HIGH otherwise (default, including empty/None).
    """
    if not log_tail:
        return ErrorPriority.HIGH

    lower = log_tail.lower()
    for pattern in _LOW_PRIORITY_PATTERNS:
        if pattern in lower:
            return ErrorPriority.LOW

    return ErrorPriority.HIGH


# ---------------------------------------------------------------------------
# Job-level detail
# ---------------------------------------------------------------------------

_JOB_TYPE_LABELS: dict[str, str] = {
    "monthly_reports": "Monthly Reports",
    "daily_usage": "Daily Usage",
    "pdf_invoice": "PDF Invoice",
}


def job_type_label(job_type: str) -> str:
    """Return a human-readable label for a scraper job type string."""
    return _JOB_TYPE_LABELS.get(job_type, job_type.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Frozen dataclasses — all pure value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorJobDetail:
    """Detail record for a single errored scraper job within a cell summary."""

    job_id: int
    priority: ErrorPriority
    completed_at: Optional[datetime]
    log_tail: Optional[str]


@dataclass(frozen=True)
class CellErrorSummary:
    """
    Aggregate error data for one (carrier, job_type) cell within the 24-hour window.

    ``priority`` reflects the *worst-case* priority across all jobs in the
    cell: HIGH if any job is HIGH, LOW only if every job is LOW.
    """

    carrier: str
    job_type: str
    job_type_label: str
    error_count: int
    high_count: int
    low_count: int
    priority: ErrorPriority  # worst-case: HIGH if high_count > 0
    accounts_affected: int
    clients_affected: int
    jobs: list[ErrorJobDetail]
    last_error_at: Optional[datetime]


@dataclass(frozen=True)
class CellHealth:
    """Health statistics for one (carrier, job_type) cell over a rolling window."""

    carrier: str
    job_type: str
    job_type_label: str
    success: int
    error: int
    success_pct: Optional[float]  # None when denominator is 0
    succeeded_after_retry: int
    avg_retries_on_success: Optional[float]  # None when no successes
    last_success: Optional[datetime]
    last_error: Optional[datetime]


@dataclass(frozen=True)
class ZombieJob:
    """
    A scraper job stuck in ``in_progress`` or ``running`` state.

    These jobs never wrote a terminal status (success / error), which means
    the processor crashed mid-run.  They are invisible to the success/error
    health matrix and must be monitored separately.
    """

    job_id: int
    carrier: str
    job_type: str
    job_type_label: str
    status: str
    account_number: str
    retry_count: int
    available_at: Optional[datetime]


@dataclass(frozen=True)
class SilentGap:
    """
    A monthly-reports job that succeeded but whose billing-cycle files are
    not fully processed.

    Treat these as *investigate* rather than confirmed failures: file status
    may be updated asynchronously by the backend after the scraper uploads.
    """

    job_id: int
    carrier: str
    account_number: str
    billing_cycle_id: int
    completed_at: Optional[datetime]
    total_files: int
    processed: int
    error_files: int
    still_to_fetch: int
    not_processed: int


@dataclass(frozen=True)
class RunRate:
    """
    Yesterday's job throughput compared to the trailing 7-day average.

    ``flagged`` is True when the trailing average is positive and yesterday's
    finished count was less than half of that average — a signal that the
    scheduler or processor may have had an outage.
    """

    yesterday: date
    yesterday_finished: int
    yesterday_success: int
    yesterday_error: int
    trailing_7d_avg: float
    flagged: bool


@dataclass(frozen=True)
class DigestData:
    """
    Complete payload for the daily scraper health digest email.

    All data is pre-computed by ``ScraperDigestService.build_digest()``; the
    mailable and template are pure consumers of this object.
    """

    report_date: date
    window_start: datetime
    window_end: datetime

    # Ordered: HIGH cells first, then by error_count desc
    errors_by_cell: list[CellErrorSummary]
    # Ordered: success_pct asc, None last
    health_context: list[CellHealth]
    # Ordered: available_at asc, NULL first
    zombies: list[ZombieJob]
    # Ordered: not_processed desc
    silent_gaps: list[SilentGap]

    run_rate: RunRate

    # Aggregated counts
    error_count: int
    high_error_count: int
    low_error_count: int
    zombie_count: int

    # Global 24-hour success percentage; None when no jobs finished
    success_pct: Optional[float]

    # Deep-link to the scraper jobs list in the frontend
    alerts_url: str

    @property
    def all_green(self) -> bool:
        """
        True when there is nothing actionable in this digest:
        no errors, no zombies, no silent gaps, and the run-rate is normal.
        """
        return self.error_count == 0 and self.zombie_count == 0 and not self.silent_gaps and not self.run_rate.flagged
