"""
Main ScraperJob processor with available_at support
"""

import logging
import os
import sys
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

import django

# Configure Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from web_scrapers.application.safe_scraper_job_service import SafeScraperJobService
from web_scrapers.application.scraper_job_service import ScraperJobService
from web_scrapers.application.services.email_service import DjangoEmailBackend, EmailService
from web_scrapers.application.session_manager import SessionManager
from web_scrapers.domain.entities.models import ScraperJobCompleteContext
from web_scrapers.domain.entities.scraper_factory import ScraperStrategyFactory
from web_scrapers.domain.entities.session import Carrier as CarrierEnum, Credentials
from web_scrapers.domain.enums import Navigators, ScraperJobStatus, ScraperType
from web_scrapers.domain.mailables.scraper_execution_log import ScraperExecutionLogMailable
from web_scrapers.infrastructure.logging_config import build_run_log_path, get_logger, setup_logging


class ScraperJobProcessor:
    """Main ScraperJob processor using clean architecture"""

    def __init__(self):
        self.logger = get_logger("scraper_job_processor")
        # Use SafeScraperJobService to handle async context after Playwright execution
        original_service = ScraperJobService()
        self.scraper_job_service = SafeScraperJobService(original_service)
        self.session_manager = SessionManager(browser_type=Navigators.CHROME)
        self.scraper_factory = ScraperStrategyFactory()
        # Per-run job results captured for the execution log email
        self.job_results: list[dict] = []

    def log_statistics(self) -> None:
        """Display available scraper statistics"""
        stats = self.scraper_job_service.get_scraper_statistics()
        self.logger.info(
            f"Scraper statistics: {stats.available_now} available now, "
            f"{stats.future_scheduled} scheduled for future, "
            f"{stats.total_pending} total pending"
        )

    def _log_retry_result(self, job_id: int, handle_result: dict) -> None:
        """Log information about retry scheduling"""
        if handle_result.get("retry_scheduled"):
            next_at = handle_result.get("next_available_at")
            next_at_str = next_at.strftime("%Y-%m-%d %H:%M:%S") if next_at else "unknown"
            self.logger.warning(
                f"Job {job_id} failed. {handle_result['message']}. "
                f"Next attempt scheduled for: {next_at_str}"
            )
        else:
            self.logger.error(f"Job {job_id} failed permanently. {handle_result['message']}")

    def process_scraper_job(self, job_context: ScraperJobCompleteContext, job_number: int, total_jobs: int) -> bool:
        """
        Process a single scraper job.

        Args:
            job_context: Complete job context with Pydantic models
            job_number: Current job number
            total_jobs: Total jobs to process

        Returns:
            True if processing was successful, False otherwise
        """
        # Extract Pydantic entities from complete context model
        scraper_job = job_context.scraper_job
        scraper_config = job_context.scraper_config
        billing_cycle = job_context.billing_cycle  # Complete with files
        credential = job_context.credential
        account = job_context.account
        carrier = job_context.carrier
        client = job_context.client

        result_entry: dict = {
            "job_id": scraper_job.id,
            "carrier": carrier.name,
            "scraper_type": scraper_job.type,
            "client": client.name,
            "account": account.number,
            "status": "FAILED",
            "error": None,
        }
        self.job_results.append(result_entry)

        self.logger.info(f"Processing job {job_number}/{total_jobs}")
        self.logger.info(f"Job ID: {scraper_job.id}")
        self.logger.info(f"Type: {scraper_job.type}")
        self.logger.info(f"Carrier: {carrier.name}")
        self.logger.info(f"Account: {account.number}")
        self.logger.info(f"Available at: {scraper_job.available_at}")

        try:
            # Update status to RUNNING
            self.scraper_job_service.update_scraper_job_status(
                scraper_job.id,
                ScraperJobStatus.RUNNING,
                f"Starting processing - Carrier: {carrier.name}, Type: {scraper_job.type}",
            )

            carrier_enum = CarrierEnum(carrier.name)
            credentials = Credentials(
                id=credential.id,
                username=credential.username,
                password=credential.get_decrypted_password(),
                carrier=carrier_enum,
            )

            scraper_type = ScraperType(scraper_job.type)

            # Session management - always delegate to SessionManager which handles:
            # 1. Same carrier + same credentials + same scraper_type → reuse session
            # 2. Same carrier + same credentials + different scraper_type → check login URL
            #    - Same login URL → reuse session
            #    - Different login URL → logout and re-login (e.g., Bell Enterprise vs Bell old portal)
            # 3. Different carrier or credentials → logout and re-login
            if self.session_manager.is_logged_in():
                current_carrier = self.session_manager.get_current_carrier()
                current_credentials = self.session_manager.get_current_credentials()
                self.logger.info(
                    f"Active session for {current_carrier.value if current_carrier else 'Unknown'} with user {current_credentials.username if current_credentials else 'N/A'}"
                )

            # Always call session_manager.login() - it handles session reuse logic internally
            login_success = self.session_manager.login(credentials, scraper_type=scraper_type)

            if not login_success:
                error_msg = "Authentication failed"
                if self.session_manager.has_error():
                    error_msg = f"Authentication failed: {self.session_manager.get_error_message()}"
                self.logger.error(error_msg)
                raise Exception(error_msg)

            self.logger.info("Authentication successful")

            # Get browser wrapper after successful authentication
            browser_wrapper = self.session_manager.get_browser_wrapper()
            if not browser_wrapper:
                raise Exception("Failed to get browser wrapper after successful authentication")

            # Create scraper using factory (like in example)
            scraper_strategy = self.scraper_factory.create_scraper(
                carrier=carrier_enum,
                scraper_type=scraper_job.type,
                browser_wrapper=browser_wrapper,
                job_id=scraper_job.id,
            )

            self.logger.info(f"Scraper created successfully: {scraper_strategy.__class__.__name__}")

            # Execute actual scraper with complete Pydantic structures
            result = scraper_strategy.execute(scraper_config, billing_cycle, credentials)

            if result.success:
                self.logger.info(f"Scraper executed successfully: {result.message}")
                self.logger.info(f"Files processed: {len(result.files)}")

                # Handle successful result
                handle_result = self.scraper_job_service.handle_job_result(
                    scraper_job.id,
                    success=True,
                    error_message=f"Scraper executed successfully: {result.message}",
                )
                self.logger.info(f"Job {scraper_job.id}: {handle_result['message']}")
                result_entry["status"] = "SUCCESS"
                return True
            else:
                self.logger.error(f"Scraper execution failed: {result.error}")

                # Handle failed result - may schedule retry
                handle_result = self.scraper_job_service.handle_job_result(
                    scraper_job.id,
                    success=False,
                    error_message=f"Scraper execution failed: {result.error}",
                )
                self._log_retry_result(scraper_job.id, handle_result)
                result_entry["error"] = str(result.error)
                return False

        except Exception as e:
            error_msg = f"Error processing scraper: {str(e)}"
            self.logger.error(error_msg, exc_info=True)

            # Handle exception - may schedule retry
            handle_result = self.scraper_job_service.handle_job_result(
                scraper_job.id,
                success=False,
                error_message=error_msg,
            )
            self._log_retry_result(scraper_job.id, handle_result)
            result_entry["error"] = str(e)
            return False

    def execute_available_scrapers(self) -> None:
        """Main function that retrieves and executes available scrapers"""
        self.logger.info("Fetching available scraper jobs...")

        # Display statistics
        self.log_statistics()

        # Get available jobs with complete context (like scraper_system_example.py)
        available_jobs = self.scraper_job_service.get_available_jobs_with_complete_context()

        if not available_jobs:
            self.logger.info("No scraper jobs available for execution at this time")
            return

        self.logger.info(f"Found {len(available_jobs)} scraper jobs available for execution")

        # Process each job
        successful_jobs = 0
        failed_jobs = 0

        for i, job_context in enumerate(available_jobs, 1):
            success = self.process_scraper_job(job_context, i, len(available_jobs))
            if success:
                successful_jobs += 1
            else:
                failed_jobs += 1

        # Final summary
        self.logger.info("Execution summary:")
        self.logger.info(f"Successful: {successful_jobs}")
        self.logger.info(f"Failed: {failed_jobs}")
        self.logger.info(f"Total processed: {len(available_jobs)}")


def _send_execution_log_email(
    log_path,
    started_at: datetime,
    finished_at: datetime,
    job_results: list[dict],
    fatal_error: str | None,
    logger,
) -> None:
    """Build and send the per-run execution-log digest email — only when at
    least one job failed or a fatal processor error occurred. Successful
    runs do not generate an email."""
    failed_results = [r for r in job_results if r["status"] != "SUCCESS"]
    successful = len(job_results) - len(failed_results)

    if not fatal_error and not failed_results:
        logger.info("All scraper jobs succeeded — skipping execution-log email")
        return

    overall_status = "FATAL" if fatal_error else ("PARTIAL" if successful else "FAILED")

    mailable = ScraperExecutionLogMailable(
        run_started_at=started_at.strftime("%Y-%m-%d %H:%M:%S"),
        run_finished_at=finished_at.strftime("%Y-%m-%d %H:%M:%S"),
        subject_timestamp=finished_at.strftime("%m-%d-%Y %H:%M"),
        total_jobs=len(job_results),
        successful_jobs=successful,
        failed_jobs=len(failed_results),
        job_results=failed_results,
        log_file_path=str(log_path) if log_path else None,
        overall_status=overall_status,
        fatal_error=fatal_error,
    )

    try:
        EmailService(DjangoEmailBackend()).send(mailable)
        logger.info("Execution-log email dispatched")
    except Exception as e:
        logger.error(f"Failed to send execution-log email: {e}", exc_info=True)


def main():
    """Main processor function"""
    started_at = datetime.now()
    log_path = build_run_log_path(now=started_at)
    setup_logging(log_level="INFO", log_file=str(log_path))
    logger = get_logger("main")
    logger.info(f"Run log file: {log_path}")

    processor = None
    fatal_error: str | None = None

    try:
        logger.info("Starting ScraperJob processor")
        processor = ScraperJobProcessor()
        processor.execute_available_scrapers()
        logger.info("ScraperJob processor completed successfully")
    except Exception as e:
        fatal_error = str(e)
        logger.error(f"Error in main processor: {fatal_error}", exc_info=True)
    finally:
        if processor and processor.session_manager:
            logger.info("Cleaning up browser resources...")
            processor.session_manager.cleanup()
            logger.info("Cleanup completed")

        finished_at = datetime.now()
        job_results = processor.job_results if processor else []
        # Flush handlers so the attachment includes everything written so far.
        for handler in logging.getLogger().handlers:
            handler.flush()
        _send_execution_log_email(
            log_path=log_path,
            started_at=started_at,
            finished_at=finished_at,
            job_results=job_results,
            fatal_error=fatal_error,
            logger=logger,
        )


if __name__ == "__main__":
    main()
