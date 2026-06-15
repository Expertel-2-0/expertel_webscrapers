"""
Domain entities for the daily scraper health digest.

This module defines the pure data structures used to represent the daily
scraper health report.  Nothing here touches the database or sends email —
those concerns belong to the application and infrastructure layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
# Triage lane classification (who needs to act)
# ---------------------------------------------------------------------------

# Not-recoverable: nothing a developer or the customer can fix.  The
# orchestration scheduled a job that can never succeed — a deleted
# client/workspace (HTTP 403 on upload) or a statement the carrier portal no
# longer retains.  These should stop being scheduled, not investigated.
_NOT_RECOVERABLE_PATTERNS: tuple[str, ...] = (
    "validate user's client",
    "client and/or workspace",
    "month not found",
    "not found in year",
    "no option found matching pattern",
    "statement not available",
    "no longer retained",
)

# Credential / access errors — fixable by the customer updating their carrier
# portal login.  Reuses the same keyword set that marks an error LOW.
_CREDENTIAL_PATTERNS: tuple[str, ...] = _LOW_PRIORITY_PATTERNS

# A (carrier, job_type) cell running at or above this 7-day success rate is
# considered healthy.  An auth failure on a HEALTHY cell is an isolated bad
# credential → SUPPORT contacts the customer.  An auth failure on an UNHEALTHY
# cell (every account failing) signals a portal-wide login break → DEV fixes
# the integration.  This is the single tunable knob for the dev/support split.
SUPPORT_HEALTH_THRESHOLD: float = 50.0


class Lane(str, Enum):
    """Triage lane — who must act on a group of scraper errors."""

    DEV = "dev"            # fix the scraper / carrier integration (code change)
    SUPPORT = "support"    # contact the customer for fresh portal credentials
    NOACTION = "noaction"  # not recoverable — orchestration should stop scheduling


def is_credential_error(log_tail: str | None) -> bool:
    """True when the log tail matches a credential/access keyword."""
    if not log_tail:
        return False
    lower = log_tail.lower()
    return any(p in lower for p in _CREDENTIAL_PATTERNS)


def is_not_recoverable(log_tail: str | None) -> bool:
    """True when the log tail matches a not-recoverable keyword."""
    if not log_tail:
        return False
    lower = log_tail.lower()
    return any(p in lower for p in _NOT_RECOVERABLE_PATTERNS)


def classify_cell_lane(jobs: list["ErrorJobDetail"], success_pct: Optional[float]) -> Lane:
    """
    Decide the triage lane for a (carrier, job_type) cell.

    Rules (evaluated in order):
      1. Every job is not-recoverable  → NOACTION.
      2. Any genuine code/site error   → DEV (dominates the cell).
      3. All remaining are credential errors:
           - cell is healthy (success_pct >= SUPPORT_HEALTH_THRESHOLD) → SUPPORT
             (isolated bad password while other accounts on the cell work).
           - otherwise → DEV (every account failing = portal-wide login break).

    ``success_pct`` is the cell's 7-day success rate (None when unknown).
    """
    if not jobs:
        return Lane.NOACTION

    recoverable = [j for j in jobs if not is_not_recoverable(j.log_tail)]
    if not recoverable:
        return Lane.NOACTION

    credential = [j for j in recoverable if is_credential_error(j.log_tail)]
    has_dev_error = len(credential) < len(recoverable)
    if has_dev_error:
        return Lane.DEV

    # All recoverable jobs are credential/auth failures.
    if success_pct is not None and success_pct >= SUPPORT_HEALTH_THRESHOLD:
        return Lane.SUPPORT
    return Lane.DEV


def cell_error_label(jobs: list["ErrorJobDetail"], lane: Lane) -> str:
    """Return a short human label for a cell's dominant error class (for the UI chip)."""
    if lane == Lane.SUPPORT:
        return "Invalid credentials"
    if lane == Lane.NOACTION:
        return "Not recoverable"

    blob = " ".join((j.log_tail or "").lower() for j in jobs)
    if any(k in blob for k in ("files section", "selector", "not found", "layout", "element")):
        return "Carrier site change"
    if any(k in blob for k in ("download",)):
        return "Download failed"
    if any(k in blob for k in ("zip", "extract", "badzipfile", "corrupt")):
        return "File processing error"
    if any(k in blob for k in ("upload", "403")):
        return "Upload failed"
    if any(k in blob for k in ("timeout", "timed out")):
        return "Timeout / site change"
    if any(k in blob for k in ("login failed", "authentication", "sign in", "sign-in")):
        return "Portal login break"
    return "Needs investigation"


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
    client_name: str = ""
    account_number: str = ""


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
    # Triage + prioritization (added by the redesign)
    lane: Lane = Lane.DEV
    error_label: str = "Needs investigation"
    days_broken: Optional[int] = None  # days since the cell last succeeded
    is_new: bool = False  # was healthy within ~48h, now failing = broke today

    @property
    def broken_label(self) -> str:
        """Human phrase for how long this cell has been broken (for the UI)."""
        if self.days_broken is None:
            return "7+ days"
        if self.days_broken == 0:
            return "today"
        if self.days_broken == 1:
            return "1 day"
        return f"{self.days_broken} days"

    @property
    def worst_log_tail(self) -> str:
        """Most-recent job's log tail, for the collapsible evidence block."""
        return self.jobs[0].log_tail if self.jobs and self.jobs[0].log_tail else ""


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

    # ── Lane split (added by the redesign) ──────────────────────────────
    # errors_by_cell partitioned by triage lane.  The template renders one
    # section per lane and hides empty lanes.
    dev_cells: list[CellErrorSummary] = field(default_factory=list)
    support_cells: list[CellErrorSummary] = field(default_factory=list)
    noaction_cells: list[CellErrorSummary] = field(default_factory=list)

    dev_job_count: int = 0
    support_job_count: int = 0
    noaction_job_count: int = 0

    @property
    def all_green(self) -> bool:
        """
        True when there is nothing actionable in this digest:
        no errors, no zombies, no silent gaps, and the run-rate is normal.
        """
        return self.error_count == 0 and self.zombie_count == 0 and not self.silent_gaps and not self.run_rate.flagged
