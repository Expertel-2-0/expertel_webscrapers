"""
Daily scraper health digest mailable.

Sends a once-per-day email to the Expertel operations team summarising the
scraper health across all (carrier, job_type) cells.  The email is always
sent — even when everything is green — so the absence of an email is itself
a signal of a problem (heartbeat pattern).
"""

from __future__ import annotations

from django.conf import settings

from web_scrapers.domain.digest import DigestData, ErrorPriority
from web_scrapers.domain.mailables.base import Mailable


class ScraperDailyDigestMailable(Mailable):
    """
    Mailable for the daily scraper health digest sent to the Expertel
    operations team.

    The mailable is a pure function of a ``DigestData`` value object — it
    performs no database access and no business logic.  All data must be
    fully assembled by ``ScraperDigestService.build_digest()`` before
    constructing this object.
    """

    def __init__(self, digest: DigestData) -> None:
        """
        Parameters
        ----------
        digest:
            Fully assembled DigestData produced by ScraperDigestService.
        """
        self.digest = digest

    # ------------------------------------------------------------------
    # Mailable contract
    # ------------------------------------------------------------------

    def get_subject(self) -> str:
        """
        Get the email subject line.

        All-green variant:
            ``[Digest] Scrapers — all green (YYYY-MM-DD)``

        Error variant:
            ``[Digest] Scrapers — N errors (H high / L low), Z zombies, P% success (YYYY-MM-DD)``
        """
        d = self.digest
        report_date = d.report_date.isoformat()

        if d.all_green:
            return f"[Digest] Scrapers — all green ({report_date})"

        pct = f"{d.success_pct:.1f}" if d.success_pct is not None else "n/a"
        return (
            f"[Digest] Scrapers — {d.dev_job_count} dev-fix / "
            f"{d.support_job_count} support, "
            f"{d.zombie_count} zombies, {pct}% success ({report_date})"
        )

    def get_to(self) -> list[str]:
        """Get the recipient list from settings.SCRAPER_ALERT_EMAILS."""
        return settings.SCRAPER_ALERT_EMAILS

    def get_from_email(self) -> str:
        """Get the sender address from settings.EMAIL_FROM_ADDRESS."""
        return settings.EMAIL_FROM_ADDRESS

    def get_template(self) -> str:
        """Get the HTML template path."""
        return "emails/content/scraper_daily_digest.html"

    def get_context(self) -> dict:
        """
        Build the template context from DigestData.

        ``priority_high`` is passed explicitly so that Django templates (which
        cannot access Python enum classes directly) can compare cell priorities
        with ``{% if cell.priority == priority_high %}``.
        """
        d = self.digest
        return {
            "report_date": d.report_date,
            "all_green": d.all_green,
            "error_count": d.error_count,
            "high_error_count": d.high_error_count,
            "low_error_count": d.low_error_count,
            "zombie_count": d.zombie_count,
            "success_pct": d.success_pct,
            "errors_by_cell": d.errors_by_cell,
            "health_context": d.health_context,
            "zombies": d.zombies,
            "silent_gaps": d.silent_gaps,
            "run_rate": d.run_rate,
            "alerts_url": d.alerts_url,
            "window_start": d.window_start,
            "window_end": d.window_end,
            "priority_high": ErrorPriority.HIGH,
            # Lane-split triage (redesign)
            "dev_cells": d.dev_cells,
            "support_cells": d.support_cells,
            "noaction_cells": d.noaction_cells,
            "dev_job_count": d.dev_job_count,
            "support_job_count": d.support_job_count,
            "noaction_job_count": d.noaction_job_count,
            # Root-cause grouping (v2 redesign)
            "dev_groups": d.dev_groups,
            "support_groups": d.support_groups,
            "noaction_groups": d.noaction_groups,
            "zombie_groups": d.zombie_groups,
            "zombie_oldest": d.zombie_oldest,
            "dev_flow_count": d.dev_flow_count,
        }

    def get_text_content(self) -> str:
        """
        Plain-text fallback for email clients that do not render HTML.

        Includes a summary header, one line per error cell, one per zombie,
        one per silent gap, and the run-rate line.  When all_green is True a
        short positive paragraph is emitted instead.
        """
        d = self.digest
        lines: list[str] = []

        lines.append(f"Scraper Health Digest — {d.report_date.isoformat()}")
        lines.append(
            f"Window: {d.window_start.strftime('%Y-%m-%d %H:%M')} UTC "
            f"to {d.window_end.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        lines.append("")

        if d.all_green:
            lines.append("All systems green. No errors, zombies, or silent gaps detected.")
            lines.append("")
            lines.append(f"View scraper jobs: {d.alerts_url}")
            return "\n".join(lines)

        # Summary
        pct_str = f"{d.success_pct:.1f}%" if d.success_pct is not None else "n/a"
        lines.append(
            f"Summary: {d.dev_job_count} dev-fix / {d.support_job_count} support"
            + (f" / {d.noaction_job_count} no-action" if d.noaction_job_count else "")
            + f", {d.zombie_count} zombies, {pct_str} success (24h)"
        )
        lines.append("")

        def _emit_cells(header: str, cells: list) -> None:
            if not cells:
                return
            lines.append(f"=== {header} ===")
            for cell in cells:
                new_flag = " [NEW today]" if cell.is_new else ""
                broken = f"{cell.days_broken}d" if cell.days_broken is not None else "7+d"
                lines.append(
                    f"  {cell.carrier} / {cell.job_type_label} — {cell.error_label}{new_flag} "
                    f"({cell.error_count} jobs, {cell.clients_affected} clients, broken {broken})"
                )
                for j in cell.jobs:
                    when = j.completed_at.strftime("%Y-%m-%d %H:%M") if j.completed_at else "unknown"
                    lines.append(f"      job#{j.job_id} — {j.client_name} / acct {j.account_number} — failed {when}")
            lines.append("")

        # Developer action — fix the scraper
        _emit_cells("DEVELOPER ACTION — fix the scraper", d.dev_cells)
        # Support action — contact the customer
        _emit_cells("SUPPORT ACTION — contact the customer", d.support_cells)
        # No action — not recoverable (only when present)
        _emit_cells("NO ACTION — not recoverable", d.noaction_cells)

        # Zombies
        if d.zombies:
            lines.append("=== ZOMBIE JOBS ===")
            for z in d.zombies:
                avail = z.available_at.strftime("%Y-%m-%d %H:%M") if z.available_at else "unknown"
                lines.append(
                    f"  Job {z.job_id} — {z.carrier} / {z.job_type_label} "
                    f"({z.status}) — account: {z.account_number} — "
                    f"retries: {z.retry_count} — available_at: {avail}"
                )
            lines.append("")

        # Silent gaps
        if d.silent_gaps:
            lines.append("=== SILENT GAPS (success jobs with unprocessed files) ===")
            for gap in d.silent_gaps:
                completed = gap.completed_at.strftime("%Y-%m-%d %H:%M") if gap.completed_at else "unknown"
                lines.append(
                    f"  Job {gap.job_id} — {gap.carrier} / {gap.account_number} "
                    f"(cycle {gap.billing_cycle_id}) — "
                    f"total: {gap.total_files}, processed: {gap.processed}, "
                    f"not processed: {gap.not_processed} — completed: {completed}"
                )
            lines.append(
                "  Note: file statuses may be updated asynchronously — "
                "treat these as 'investigate', not confirmed failures."
            )
            lines.append("")

        # Run rate
        rr = d.run_rate
        lines.append("=== RUN RATE ===")
        lines.append(
            f"  Yesterday ({rr.yesterday.isoformat()}): "
            f"{rr.yesterday_finished} finished "
            f"({rr.yesterday_success} success / {rr.yesterday_error} error) "
            f"vs 7-day avg {rr.trailing_7d_avg:.1f}"
        )
        if rr.flagged:
            lines.append(
                "  WARNING: yesterday's throughput is less than 50% of the "
                "7-day average — possible scheduler or processor outage."
            )
        lines.append("")
        lines.append(f"View scraper jobs: {d.alerts_url}")

        return "\n".join(lines)
