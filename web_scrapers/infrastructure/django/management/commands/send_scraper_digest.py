"""
Management command: send_scraper_digest

Builds and sends the daily scraper health digest email to all addresses
configured in settings.SCRAPER_ALERT_EMAILS.

The digest is sent on *every* run — including when all scrapers are healthy
(all_green == True).  This heartbeat pattern means that the *absence* of an
email is itself a signal that the command or its scheduler has failed.

Usage
-----
    python manage.py send_scraper_digest
    python manage.py send_scraper_digest --dry-run
"""

import logging

from django.core.management.base import BaseCommand, CommandError

from web_scrapers.application.services.email_service import (
    DjangoEmailBackend,
    EmailService,
)
from web_scrapers.application.services.scraper_digest_service import ScraperDigestService
from web_scrapers.domain.mailables.scraper_daily_digest import ScraperDailyDigestMailable

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Send the daily scraper health digest email.

    Builds a DigestData snapshot with ScraperDigestService, wraps it in a
    ScraperDailyDigestMailable, and sends it via Django's email backend.

    The email is always sent, even when no errors were detected (heartbeat).
    Pass --dry-run to print the subject, recipients, text body, and a
    brief context summary without sending anything.
    """

    help = (
        "Send the daily scraper health digest email.  "
        "Sent unconditionally (heartbeat pattern) — absence of the email "
        "indicates that the command or its scheduler has failed."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print the email subject, recipients, text body, and digest summary without sending.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        dry_run: bool = options["dry_run"]

        try:
            service = ScraperDigestService()
            digest = service.build_digest()
            mailable = ScraperDailyDigestMailable(digest)

            subject = mailable.get_subject()
            recipients = mailable.get_to()
            text_body = mailable.get_text_content()

            if dry_run:
                self.stdout.write(self.style.WARNING("[DRY RUN] No email will be sent.\n"))
                self.stdout.write(f"Subject   : {subject}\n")
                self.stdout.write(f"To        : {', '.join(recipients)}\n")
                self.stdout.write(f"Report    : {digest.report_date}\n")
                self.stdout.write(
                    f"Window    : {digest.window_start.strftime('%Y-%m-%d %H:%M')} UTC "
                    f"→ {digest.window_end.strftime('%Y-%m-%d %H:%M')} UTC\n"
                )
                self.stdout.write(
                    f"Errors    : {digest.error_count} "
                    f"({digest.high_error_count} high / {digest.low_error_count} low)\n"
                )
                self.stdout.write(f"Zombies   : {digest.zombie_count}\n")
                self.stdout.write(f"Gaps      : {len(digest.silent_gaps)}\n")
                pct = f"{digest.success_pct:.1f}%" if digest.success_pct is not None else "n/a"
                self.stdout.write(f"Success % : {pct} (24h)\n")
                self.stdout.write(f"All green : {digest.all_green}\n")
                self.stdout.write("\n--- TEXT BODY ---\n")
                self.stdout.write(text_body)
                self.stdout.write("\n--- END ---\n")
                return

            email_service = EmailService(DjangoEmailBackend())
            email_service.send(mailable)

            self.stdout.write(self.style.SUCCESS(f"SUCCESS Digest sent: {subject}"))

        except Exception as exc:
            logger.exception("send_scraper_digest failed: %s", exc)
            raise CommandError(f"Failed to send scraper digest: {exc}") from exc
