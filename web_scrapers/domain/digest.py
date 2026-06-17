"""
Domain entities for the daily scraper health digest.

This module defines the pure data structures used to represent the daily
scraper health report.  Nothing here touches the database or sends email —
those concerns belong to the application and infrastructure layers.
"""

from __future__ import annotations

from collections import defaultdict
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

    DEV = "dev"  # fix the scraper / carrier integration (code change)
    SUPPORT = "support"  # contact the customer for fresh portal credentials
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


# Compact labels for inline narrative ("Rogers Daily 11%") where the full
# "Daily Usage" / "Monthly Reports" wording would be too verbose.
_JOB_TYPE_SHORT: dict[str, str] = {
    "monthly_reports": "Monthly",
    "daily_usage": "Daily",
    "pdf_invoice": "PDF",
}


def job_type_short(job_type: str) -> str:
    """Return a compact label for a scraper job type (for inline narrative)."""
    return _JOB_TYPE_SHORT.get(job_type, job_type_label(job_type))


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
    success_pct: Optional[float] = None  # 7-day success rate (for inline narrative)

    @property
    def broken_label(self) -> str:
        """Human phrase for how long this cell has been broken (for the UI)."""
        if self.days_broken is None:
            return "7+ days"
        if self.days_broken == 0:
            return "<1 day"
        if self.days_broken == 1:
            return "1 day"
        return f"{self.days_broken} days"

    @property
    def health_label(self) -> str:
        """Compact '{carrier} {short type} {pct}%' label for inline narrative."""
        pct = f"{self.success_pct:.0f}%" if self.success_pct is not None else "n/a"
        return f"{self.carrier} {job_type_short(self.job_type)} {pct}"

    @property
    def broken_phrase(self) -> str:
        """'{carrier} {short type} broken {broken_label}' for the since line."""
        return f"{self.carrier} {job_type_short(self.job_type)} broken {self.broken_label}"

    @property
    def worst_log_tail(self) -> str:
        """Most-recent job's log tail, for the collapsible evidence block."""
        return self.jobs[0].log_tail if self.jobs and self.jobs[0].log_tail else ""


# ---------------------------------------------------------------------------
# Root-cause grouping (consolidate cells that share one underlying failure)
# ---------------------------------------------------------------------------

# Per error class: the chip CSS class the template should use, and the phrase
# that completes the consolidated card title ("{carriers} — {phrase}").
_ROOT_CAUSE_COPY: dict[str, tuple[str, str]] = {
    "Portal login break": ("chip-login", "login down fleet-wide"),
    "Carrier site change": ("chip-site", "page changed — element no longer found"),
    "Timeout / site change": ("chip-site", "timing out — likely a site change"),
    "Download failed": ("chip-download", "download step failing"),
    "File processing error": ("chip-download", "file processing failing"),
    "Upload failed": ("chip-download", "upload to backend failing"),
    "Invalid credentials": ("chip-creds", "logins rejected"),
    "Not recoverable": ("chip-noop", "not recoverable"),
    "Needs investigation": ("chip-dev", "needs investigation"),
}


@dataclass(frozen=True)
class RootCauseGroup:
    """
    A set of (carrier, job_type) error cells that share the same triage lane,
    dominant error class, and NEW/ongoing status — consolidated into a single
    issue card.

    Cells are grouped because one root cause (a carrier login break, a page
    redesign, a dead stored credential) explains all of them, so the digest
    presents one diagnosis and one action instead of repeating it per cell.
    """

    lane: Lane
    error_label: str
    is_new: bool
    cells: list[CellErrorSummary]

    @property
    def total_jobs(self) -> int:
        """Total failed jobs across every cell in the group."""
        return sum(c.error_count for c in self.cells)

    @property
    def flow_count(self) -> int:
        """Number of distinct (carrier, job_type) flows in this group."""
        return len(self.cells)

    @property
    def total_accounts(self) -> int:
        """Sum of distinct accounts affected across the group's cells."""
        return sum(c.accounts_affected for c in self.cells)

    @property
    def total_clients(self) -> int:
        """Sum of distinct clients affected across the group's cells."""
        return sum(c.clients_affected for c in self.cells)

    @property
    def carriers(self) -> list[str]:
        """Distinct carriers in this group, preserving first-seen order."""
        seen: list[str] = []
        for c in self.cells:
            if c.carrier not in seen:
                seen.append(c.carrier)
        return seen

    @property
    def carriers_phrase(self) -> str:
        """'Rogers & T-Mobile' / 'Verizon, Bell & Telus' for the card title."""
        names = self.carriers
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} & {names[1]}"
        return ", ".join(names[:-1]) + f" & {names[-1]}"

    @property
    def title(self) -> str:
        """Human card title: '{carriers} — {root-cause phrase}'."""
        if self.lane == Lane.SUPPORT and self.error_label == "Invalid credentials":
            n = self.total_accounts
            plural = "s" if n != 1 else ""
            return f"{self.carriers_phrase} — {n} customer login{plural} rejected"
        phrase = _ROOT_CAUSE_COPY.get(self.error_label, ("chip-dev", self.error_label.lower()))[1]
        return f"{self.carriers_phrase} — {phrase}"

    @property
    def chip_class(self) -> str:
        """CSS chip class matching the group's error class."""
        return _ROOT_CAUSE_COPY.get(self.error_label, ("chip-dev", ""))[0]

    @property
    def is_fleet_wide(self) -> bool:
        """
        True only when every flow in the group is genuinely down — i.e. each
        cell's 7-day success rate is below SUPPORT_HEALTH_THRESHOLD.

        Guards the "every account fails at once / login down fleet-wide"
        narrative: when the group mixes a still-healthy flow (e.g. Bell Daily
        at 85 %) with a dead one (T-Mobile at 0 %), that framing over-claims, so
        the template falls back to neutral wording instead.
        """
        return bool(self.cells) and all(
            c.success_pct is not None and c.success_pct < SUPPORT_HEALTH_THRESHOLD for c in self.cells
        )

    @property
    def health_phrase(self) -> str:
        """'Rogers Daily 11%, T-Mobile Daily 0%' — per-flow 7-day success."""
        return ", ".join(c.health_label for c in self.cells)

    @property
    def broken_phrase(self) -> str:
        """'Rogers Daily broken 6 days, T-Mobile Daily broken 7+ days'."""
        return ", ".join(c.broken_phrase for c in self.cells)

    @property
    def sample_log(self) -> str:
        """Most-recent non-empty log tail across the group's cells."""
        for c in self.cells:
            if c.worst_log_tail:
                return c.worst_log_tail
        return ""


def group_cells_by_root_cause(cells: list[CellErrorSummary]) -> list[RootCauseGroup]:
    """
    Consolidate error cells that share ``(error_label, is_new)`` into
    RootCauseGroups.

    Cells are assumed to already belong to a single triage lane (the caller
    partitions by lane first).  Groups are ordered NEW first, then by total
    failed-job count descending so the worst, freshest breakage leads.

    Parameters
    ----------
    cells:
        Same-lane CellErrorSummary objects to consolidate.

    Returns
    -------
    list[RootCauseGroup]
    """
    buckets: dict[tuple[str, bool], list[CellErrorSummary]] = {}
    for cell in cells:
        buckets.setdefault((cell.error_label, cell.is_new), []).append(cell)

    groups = [
        RootCauseGroup(lane=members[0].lane, error_label=label, is_new=is_new, cells=members)
        for (label, is_new), members in buckets.items()
    ]
    groups.sort(key=lambda g: (not g.is_new, -g.total_jobs))
    return groups


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
class ZombieGroup:
    """
    Stuck-job count and oldest timestamp aggregated by (carrier, job_type).

    The per-job ZombieJob list is too noisy for the digest; operations only
    needs to know which (carrier, type) flows are accumulating zombies and how
    far back the backlog reaches.
    """

    carrier: str
    job_type: str
    job_type_label: str
    count: int
    oldest: Optional[datetime]


def group_zombies(zombies: list[ZombieJob]) -> list[ZombieGroup]:
    """
    Aggregate zombie jobs by (carrier, job_type): count + oldest available_at.

    ``oldest`` is the minimum non-null ``available_at`` in the bucket (None
    when every job in the bucket has a null schedule time).  Groups are sorted
    by count descending so the worst backlog leads.

    Parameters
    ----------
    zombies:
        Flat list of stuck jobs from ``get_zombie_jobs``.

    Returns
    -------
    list[ZombieGroup]
    """
    buckets: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "oldest": None, "label": ""})
    for z in zombies:
        bucket = buckets[(z.carrier, z.job_type)]
        bucket["count"] += 1
        bucket["label"] = z.job_type_label
        if z.available_at is not None and (bucket["oldest"] is None or z.available_at < bucket["oldest"]):
            bucket["oldest"] = z.available_at

    groups = [
        ZombieGroup(
            carrier=carrier,
            job_type=jtype,
            job_type_label=bucket["label"],
            count=bucket["count"],
            oldest=bucket["oldest"],
        )
        for (carrier, jtype), bucket in buckets.items()
    ]
    groups.sort(key=lambda g: -g.count)
    return groups


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

    # ── Root-cause grouping (v2 redesign) ───────────────────────────────
    # Each lane's cells consolidated into issue cards by shared error class.
    # The template renders one card per group instead of one per cell.
    dev_groups: list[RootCauseGroup] = field(default_factory=list)
    support_groups: list[RootCauseGroup] = field(default_factory=list)
    noaction_groups: list[RootCauseGroup] = field(default_factory=list)

    # Zombies aggregated by (carrier, job_type) for the stuck-jobs card.
    zombie_groups: list[ZombieGroup] = field(default_factory=list)
    zombie_oldest: Optional[datetime] = None

    # Distinct dev flows broken (= len(dev_cells)), for the lane sub-text.
    dev_flow_count: int = 0

    @property
    def all_green(self) -> bool:
        """
        True when there is nothing actionable in this digest:
        no errors, no zombies, no silent gaps, and the run-rate is normal.
        """
        return self.error_count == 0 and self.zombie_count == 0 and not self.silent_gaps and not self.run_rate.flagged
