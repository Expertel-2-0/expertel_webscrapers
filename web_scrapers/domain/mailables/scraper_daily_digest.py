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
            f"[Digest] Scrapers — {d.error_count} errors "
            f"({d.high_error_count} high / {d.low_error_count} low), "
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
            f"Summary: {d.error_count} errors "
            f"({d.high_error_count} HIGH / {d.low_error_count} LOW), "
            f"{d.zombie_count} zombies, {pct_str} success (24h)"
        )
        lines.append("")

        # Error cells
        if d.errors_by_cell:
            lines.append("=== ERRORS BY CELL (24h) ===")
            for cell in d.errors_by_cell:
                priority_label = "HIGH" if cell.priority == ErrorPriority.HIGH else "LOW"
                last_err = cell.last_error_at.strftime("%Y-%m-%d %H:%M") if cell.last_error_at else "unknown"
                lines.append(
                    f"  [{priority_label}] {cell.carrier} / {cell.job_type_label}: "
                    f"{cell.error_count} errors "
                    f"({cell.high_count} high / {cell.low_count} low) — "
                    f"accounts: {cell.accounts_affected}, "
                    f"clients: {cell.clients_affected} — "
                    f"last error: {last_err}"
                )
            lines.append("")

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
