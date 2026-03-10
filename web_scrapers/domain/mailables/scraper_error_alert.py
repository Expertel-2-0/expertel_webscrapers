"""
Scraper error alert mailable for notifying the Expertel operations team
when a scraper job encounters an error or exceeds its retry limit.
"""

from django.conf import settings

from web_scrapers.domain.mailables.base import Mailable


class ScraperErrorAlertMailable(Mailable):
    """Mailable for scraper job error alert notifications sent to the Expertel operations team."""

    def __init__(
        self,
        job_id: int,
        scraper_type: str,
        carrier_name: str,
        client_name: str,
        account_number: str,
        error_message: str,
        retry_count: int,
        max_retries: int,
        error_date: str,
        logs_url: str,
    ):
        """
        Initialize the scraper error alert mailable.

        Args:
            job_id: Primary key of the ScraperJob that failed.
            scraper_type: Human-readable scraper type label.
            carrier_name: Name of the carrier associated with the scraper config.
            client_name: Name of the client whose account is being scraped.
            account_number: Carrier account number being scraped.
            error_message: Last non-empty line from the job log, used as the error summary.
            retry_count: Number of retry attempts already made.
            max_retries: Maximum number of retries allowed for this job.
            error_date: Formatted datetime string when the error occurred.
            logs_url: Full URL to the scraper job detail page in the frontend.
        """
        self.job_id = job_id
        self.scraper_type = scraper_type
        self.carrier_name = carrier_name
        self.client_name = client_name
        self.account_number = account_number
        self.error_message = error_message
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.error_date = error_date
        self.logs_url = logs_url

    def get_subject(self) -> str:
        """Get the email subject line."""
        return f"[Alert] Scraper Error - {self.carrier_name} / {self.scraper_type}"

    def get_from_email(self) -> str:
        """Get the sender email address."""
        return settings.EMAIL_FROM_ADDRESS

    def get_to(self) -> list[str]:
        """Get the recipient email address list."""
        return settings.SCRAPER_ALERT_EMAILS

    def get_template(self) -> str:
        """Get the HTML template path for this email."""
        return "emails/content/scraper_error.html"

    def get_context(self) -> dict:
        """Get the template context variables."""
        return {
            "nombre": "Expertel Team",
            "job_id": self.job_id,
            "scraper_type": self.scraper_type,
            "carrier_name": self.carrier_name,
            "client_name": self.client_name,
            "account_number": self.account_number,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_date": self.error_date,
            "logs_url": self.logs_url,
        }

    def get_text_content(self) -> str:
        """Get the plain text fallback content for the email."""
        return (
            f"Scraper Error Alert\n\n"
            f"A scraper encountered an error on {self.error_date}.\n\n"
            f"Scraper: {self.scraper_type}\n"
            f"Carrier / Source: {self.carrier_name}\n"
            f"Client: {self.client_name}\n"
            f"Account: {self.account_number}\n"
            f"Status: Failed\n"
            f"Error: {self.error_message}\n"
            f"Attempts: {self.retry_count} of {self.max_retries} retries failed\n\n"
            f"View error logs: {self.logs_url}"
        )