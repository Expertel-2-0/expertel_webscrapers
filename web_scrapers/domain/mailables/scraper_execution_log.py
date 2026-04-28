"""
Scraper execution log mailable. Sent at the end of every scraper run with
a summary of every job processed and the full log file attached.
"""

from pathlib import Path

from django.conf import settings

from web_scrapers.domain.mailables.base import Attachment, Mailable


class ScraperExecutionLogMailable(Mailable):
    """Mailable that delivers the per-run scraper execution log digest."""

    def __init__(
        self,
        run_started_at: str,
        run_finished_at: str,
        subject_timestamp: str,
        total_jobs: int,
        successful_jobs: int,
        failed_jobs: int,
        job_results: list[dict],
        log_file_path: str | None,
        overall_status: str,
        fatal_error: str | None = None,
    ):
        self.run_started_at = run_started_at
        self.run_finished_at = run_finished_at
        self.subject_timestamp = subject_timestamp
        self.total_jobs = total_jobs
        self.successful_jobs = successful_jobs
        self.failed_jobs = failed_jobs
        self.job_results = job_results
        self.log_file_path = log_file_path
        self.overall_status = overall_status
        self.fatal_error = fatal_error

    def get_subject(self) -> str:
        return f"Scraper Execution Log {self.subject_timestamp}"

    def get_from_email(self) -> str:
        return settings.EMAIL_FROM_ADDRESS

    def get_to(self) -> list[str]:
        return settings.SCRAPER_EXECUTION_LOG_EMAILS

    def get_template(self) -> str:
        return "emails/content/scraper_execution_log.html"

    def get_context(self) -> dict:
        return {
            "run_started_at": self.run_started_at,
            "run_finished_at": self.run_finished_at,
            "total_jobs": self.total_jobs,
            "successful_jobs": self.successful_jobs,
            "failed_jobs": self.failed_jobs,
            "job_results": self.job_results,
            "overall_status": self.overall_status,
            "fatal_error": self.fatal_error,
            "log_file_name": Path(self.log_file_path).name if self.log_file_path else None,
        }

    def get_text_content(self) -> str:
        lines = [
            "Scraper Execution Log",
            "",
            f"Started:  {self.run_started_at}",
            f"Finished: {self.run_finished_at}",
            f"Status:   {self.overall_status}",
            "",
            f"Total jobs: {self.total_jobs}",
            f"Successful: {self.successful_jobs}",
            f"Failed:     {self.failed_jobs}",
        ]
        if self.fatal_error:
            lines += ["", f"Fatal error: {self.fatal_error}"]
        if self.job_results:
            lines += ["", "Per-job results:"]
            for r in self.job_results:
                err = f" - {r['error']}" if r.get("error") else ""
                lines.append(
                    f"  [{r['status']}] job#{r['job_id']} {r['carrier']}/{r['scraper_type']} "
                    f"({r['client']} / {r['account']}){err}"
                )
        if self.log_file_path:
            lines += ["", f"Full log attached: {Path(self.log_file_path).name}"]
        return "\n".join(lines)

    def get_attachments(self) -> list[Attachment]:
        if not self.log_file_path:
            return []
        path = Path(self.log_file_path)
        if not path.exists():
            return []
        return [(path.name, path.read_bytes(), "text/plain")]
