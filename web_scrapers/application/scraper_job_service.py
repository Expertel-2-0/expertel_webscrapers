"""
ScraperJobService - Service for managing ScraperJobs with available_at support
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Case, F, Q, TextField, Value, When
from django.db.models.functions import Coalesce, Concat
from django.utils import timezone

from web_scrapers.application.services.email_service import DjangoEmailBackend, EmailService
from web_scrapers.domain.entities.models import (
    Account,
    BillingCycle,
    BillingCycleDailyUsageFile,
    BillingCycleFile,
    BillingCyclePDFFile,
    Carrier,
    CarrierPortalCredential,
    CarrierReport,
    Client,
    ScraperConfig,
    ScraperJob,
    ScraperJobCompleteContext,
    ScraperStatistics,
    Workspace,
)
from web_scrapers.domain.enums import FileStatus, ScraperJobStatus, ScraperType
from web_scrapers.domain.mailables.scraper_error_alert import ScraperErrorAlertMailable
from web_scrapers.infrastructure.django.models import ScraperJob as DjangoScraperJob
from web_scrapers.infrastructure.django.repositories import (
    AccountRepository,
    BillingCycleDailyUsageFileRepository,
    BillingCycleFileRepository,
    BillingCyclePDFFileRepository,
    BillingCycleRepository,
    CarrierPortalCredentialRepository,
    CarrierReportRepository,
    CarrierRepository,
    ClientRepository,
    ScraperConfigRepository,
    ScraperJobRepository,
    WorkspaceRepository,
)

logger = logging.getLogger(__name__)


class ScraperJobService:
    """Service for managing ScraperJobs with intelligent fetch based on available_at"""

    # Retry delay configuration by scraper type
    RETRY_DELAYS = {
        ScraperType.MONTHLY_REPORTS: {"days": 1, "hour": 6},  # 1 day, at 6:00 AM
        ScraperType.PDF_INVOICE: {"days": 1, "hour": 6},  # 1 day, at 6:00 AM
        ScraperType.DAILY_USAGE: {"hours": 1},  # 1 hour from now
    }

    def __init__(self):
        # Initialize all repositories needed to build complete structures
        self.scraper_job_repo = ScraperJobRepository()
        self.scraper_config_repo = ScraperConfigRepository()
        self.billing_cycle_repo = BillingCycleRepository()
        self.credential_repo = CarrierPortalCredentialRepository()
        self.account_repo = AccountRepository()
        self.carrier_repo = CarrierRepository()
        self.workspace_repo = WorkspaceRepository()
        self.client_repo = ClientRepository()
        self.billing_cycle_file_repo = BillingCycleFileRepository()
        self.daily_usage_file_repo = BillingCycleDailyUsageFileRepository()
        self.pdf_file_repo = BillingCyclePDFFileRepository()
        self.carrier_report_repo = CarrierReportRepository()

    def get_available_scraper_jobs(self, include_null_available_at: bool = True) -> List[ScraperJob]:
        """
        Get and claim scraper jobs for execution.

        Strategy:
        - daily_usage: ALL available jobs regardless of scraper_config (avoids backlog with 30-min cycles)
        - monthly_reports / pdf_invoice: jobs from a single scraper_config (existing behavior)

        This method:
        1. Fetches all available daily_usage jobs
        2. Fetches all monthly/pdf jobs for the first available scraper_config
        3. Atomically marks the combined set as IN_PROGRESS
        4. Returns those jobs (main.py will mark them as RUNNING when executing)

        Args:
            include_null_available_at: Whether to include jobs with available_at=NULL for compatibility

        Returns:
            List of ScraperJob Pydantic entities for execution
        """
        current_time = timezone.now()

        # Orphan jobs (scraper_config IS NULL) are unrecoverable — mark them ERROR final
        # in a single UPDATE so they don't cycle through retries uselessly.
        orphan_log_entry = f"\n[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR FINAL: orphan job — missing scraper_config"
        with transaction.atomic():
            orphan_count = DjangoScraperJob.objects.filter(
                status=ScraperJobStatus.PENDING,
                scraper_config__isnull=True,
            ).update(
                status=ScraperJobStatus.ERROR,
                completed_at=current_time,
                log=Concat(
                    Coalesce(F("log"), Value("", output_field=TextField())),
                    Value(orphan_log_entry, output_field=TextField()),
                    output_field=TextField(),
                ),
            )
        if orphan_count:
            logger.error(f"Marked {orphan_count} orphan scraper_jobs as ERROR (missing scraper_config)")

        # Build base query filter for PENDING jobs
        query_filter = Q(status=ScraperJobStatus.PENDING) & Q(scraper_config__isnull=False)


        if include_null_available_at:
            query_filter &= Q(available_at__lte=current_time) | Q(available_at__isnull=True)
        else:
            query_filter &= Q(available_at__lte=current_time)

        # Custom ordering for scraper type: monthly_reports -> daily_usage -> pdf_invoice
        type_order = Case(
            When(type="monthly_reports", then=Value(1)),
            When(type="daily_usage", then=Value(2)),
            When(type="pdf_invoice", then=Value(3)),
            default=Value(99),
        )

        # --- Part 1: All available daily_usage jobs (cross-config) ---
        daily_usage_ids = list(
            DjangoScraperJob.objects.filter(
                query_filter,
                type=ScraperType.DAILY_USAGE,
            ).values_list("id", flat=True)
        )

        # --- Part 2: monthly_reports / pdf_invoice from a single scraper_config ---
        non_daily_filter = query_filter & ~Q(type=ScraperType.DAILY_USAGE)

        first_non_daily_job = (
            DjangoScraperJob.objects.filter(non_daily_filter)
            .annotate(type_order=type_order)
            .order_by("scraper_config__credential_id", "scraper_config__account_id", "type_order", "available_at")
            .first()
        )

        non_daily_ids: List[int] = []
        if first_non_daily_job:
            non_daily_ids = list(
                DjangoScraperJob.objects.filter(
                    non_daily_filter,
                    scraper_config_id=first_non_daily_job.scraper_config_id,
                ).values_list("id", flat=True)
            )

        # --- Combine both sets ---
        all_target_ids = list(set(daily_usage_ids) | set(non_daily_ids))

        if not all_target_ids:
            return []

        # Atomically mark the combined set as IN_PROGRESS
        # status=PENDING filter prevents race conditions
        updated_count = DjangoScraperJob.objects.filter(
            id__in=all_target_ids,
            status=ScraperJobStatus.PENDING,
        ).update(status=ScraperJobStatus.IN_PROGRESS)

        if updated_count == 0:
            # Another instance already claimed these jobs
            return []

        # Fetch only the jobs we successfully claimed
        django_jobs = (
            DjangoScraperJob.objects.filter(
                id__in=all_target_ids,
                status=ScraperJobStatus.IN_PROGRESS,
            )
            .annotate(type_order=type_order)
            .order_by("type_order", "available_at")
        )

        results = []
        for job in django_jobs:
            try:
                results.append(self.scraper_job_repo.to_entity(job))
            except Exception as e:
                logger.error(f"Job {job.pk} has invalid data ({e}). Marking as error.")
                self.handle_job_result(
                    job.pk,
                    success=False,
                    error_message=f"Invalid job data: {e}",
                )
        return results

    def get_scraper_job_with_complete_context(self, scraper_job_id: int) -> ScraperJobCompleteContext:
        """
        Get a scraper job with all its related context, building complete Pydantic structures
        similar to scraper_system_example.py

        Args:
            scraper_job_id: ID of the scraper job

        Returns:
            ScraperJobCompleteContext with complete assembled Pydantic structures for scraper execution
        """
        # Get Django models with all relations
        django_job = DjangoScraperJob.objects.select_related(
            "billing_cycle",
            "scraper_config",
            "scraper_config__account",
            "scraper_config__credential",
            "scraper_config__carrier",
            "billing_cycle__account",
            "billing_cycle__account__workspace",
            "billing_cycle__account__workspace__client",
            "billing_cycle__account__carrier",
        ).get(id=scraper_job_id)

        # Convert base entities using repositories (Django → Pydantic)
        scraper_job = self.scraper_job_repo.to_entity(django_job)
        scraper_config = self.scraper_config_repo.to_entity(django_job.scraper_config)
        billing_cycle = self.billing_cycle_repo.to_entity(django_job.billing_cycle)
        credential = self.credential_repo.to_entity(django_job.scraper_config.credential)
        account = self.account_repo.to_entity(django_job.billing_cycle.account)
        carrier = self.carrier_repo.to_entity(django_job.scraper_config.carrier)
        workspace = self.workspace_repo.to_entity(django_job.billing_cycle.account.workspace)
        client = self.client_repo.to_entity(django_job.billing_cycle.account.workspace.client)

        # Get related files for billing cycle and convert to Pydantic
        billing_cycle_files_django = django_job.billing_cycle.billing_cycle_files.select_related(
            "carrier_report"
        ).all()

        # Convert file collections to Pydantic
        billing_cycle_files = []
        for file_django in billing_cycle_files_django:
            file_pydantic = self.billing_cycle_file_repo.to_entity(file_django)
            # Add carrier report if exists
            if hasattr(file_django, "carrier_report") and file_django.carrier_report:
                file_pydantic.carrier_report = self.carrier_report_repo.to_entity(file_django.carrier_report)
            billing_cycle_files.append(file_pydantic)

        # Create placeholder arrays with single objects for daily and PDF files
        # These are created as placeholders since actual files don't exist until scraper execution
        daily_usage_files = [
            BillingCycleDailyUsageFile(
                id=1, billing_cycle_id=billing_cycle.id, status=FileStatus.TO_BE_FETCHED, s3_key=None
            )
        ]

        pdf_files = [
            BillingCyclePDFFile(
                id=1,
                billing_cycle_id=billing_cycle.id,
                status=FileStatus.TO_BE_FETCHED,
                status_comment="Waiting for PDF scraper execution",
                s3_key=None,
                pdf_type="invoice",
            )
        ]

        # Populate relationships
        workspace.client = client
        account.workspace = workspace

        billing_cycle.account = account
        billing_cycle.billing_cycle_files = billing_cycle_files
        billing_cycle.daily_usage_files = daily_usage_files
        billing_cycle.pdf_files = pdf_files

        # Return complete context structure as Pydantic model
        return ScraperJobCompleteContext(
            scraper_job=scraper_job,
            scraper_config=scraper_config,
            billing_cycle=billing_cycle,  # Complete with all files
            credential=credential,
            account=account,
            carrier=carrier,
            workspace=workspace,
            client=client,
        )

    def get_available_jobs_with_complete_context(
        self, include_null_available_at: bool = True
    ) -> List[ScraperJobCompleteContext]:
        """
        Get all available scraper jobs with their complete context, ready for scraper execution.
        Each job will have complete Pydantic structures like in scraper_system_example.py

        Args:
            include_null_available_at: Whether to include jobs with available_at=NULL

        Returns:
            List of ScraperJobCompleteContext with complete assembled Pydantic structures for each scraper job
        """
        available_jobs = self.get_available_scraper_jobs(include_null_available_at)

        results = []
        for job in available_jobs:
            try:
                results.append(self.get_scraper_job_with_complete_context(job.id))
            except Exception as e:
                self.logger.error(
                    f"Failed to build context for job {job.id}: {e}. "
                    f"Marking as failed and continuing with remaining jobs."
                )
                self.handle_job_result(
                    job.id,
                    success=False,
                    error_message=f"Failed to build job context: {e}",
                )
        return results

    def get_scraper_statistics(self) -> ScraperStatistics:
        """
        Get scraper statistics for logging.

        Returns:
            ScraperStatistics model with detailed statistics
        """
        current_time = timezone.now()

        total_pending = DjangoScraperJob.objects.filter(status=ScraperJobStatus.PENDING).count()

        available_now = DjangoScraperJob.objects.filter(
            status=ScraperJobStatus.PENDING, available_at__lte=current_time
        ).count()

        future_scheduled = DjangoScraperJob.objects.filter(
            status=ScraperJobStatus.PENDING, available_at__gt=current_time
        ).count()

        null_available = DjangoScraperJob.objects.filter(
            status=ScraperJobStatus.PENDING, available_at__isnull=True
        ).count()

        in_progress = DjangoScraperJob.objects.filter(status=ScraperJobStatus.IN_PROGRESS).count()

        running = DjangoScraperJob.objects.filter(status=ScraperJobStatus.RUNNING).count()

        return ScraperStatistics(
            timestamp=current_time,
            total_pending=total_pending,
            available_now=available_now,
            future_scheduled=future_scheduled,
            null_available_at=null_available,
            in_progress=in_progress,
            running=running,
        )

    def update_scraper_job_status(
        self, scraper_job_id: int, status: ScraperJobStatus, log_message: Optional[str] = None
    ) -> None:
        """
        Update the status of a scraper job.

        Args:
            scraper_job_id: ID of the scraper job
            status: New status
            log_message: Optional log message
        """
        django_job = DjangoScraperJob.objects.get(id=scraper_job_id)
        django_job.status = status

        if log_message:
            current_log = django_job.log or ""
            django_job.log = f"{current_log}\n{timezone.now()}: {log_message}".strip()

        if status in [ScraperJobStatus.SUCCESS, ScraperJobStatus.ERROR]:
            django_job.completed_at = timezone.now()

        django_job.save()

    def handle_job_result(
        self,
        scraper_job_id: int,
        success: bool,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handle the result of a job execution with retry logic.

        Logic:
        - SUCCESS: Mark as SUCCESS, completed_at = now, no more executions
        - FAIL + retry_count < max_retries:
            - retry_count += 1
            - status = PENDING (to be picked up again)
            - available_at = calculated based on scraper type:
                - MONTHLY_REPORTS: tomorrow 6:00 AM
                - PDF_INVOICE: tomorrow 6:00 AM
                - DAILY_USAGE: 1 hour from now
            - Log error with retry information
        - FAIL + retry_count >= max_retries:
            - status = ERROR (final)
            - completed_at = now
            - Log indicating max retries reached

        Args:
            scraper_job_id: Job ID
            success: True if job was successful, False if it failed
            error_message: Error message or additional information

        Returns:
            Dict with result information:
            {
                'job_id': int,
                'final_status': str,
                'retry_scheduled': bool,
                'retry_count': int,
                'next_available_at': datetime or None,
                'message': str
            }
        """
        django_job = DjangoScraperJob.objects.get(id=scraper_job_id)
        current_time = timezone.now()
        result = {
            "job_id": scraper_job_id,
            "retry_scheduled": False,
            "retry_count": django_job.retry_count,
            "next_available_at": None,
        }

        if success:
            # Job successful - mark as SUCCESS
            django_job.status = ScraperJobStatus.SUCCESS
            django_job.completed_at = current_time

            log_message = "SUCCESS: Job completed successfully"
            if error_message:
                log_message = f"SUCCESS: {error_message}"

            self._append_log(django_job, log_message)

            result["final_status"] = ScraperJobStatus.SUCCESS
            result["message"] = "Job completed successfully"

        else:
            # Job failed - check if it can retry
            if django_job.retry_count < django_job.max_retries:
                # Increment retry count first
                django_job.retry_count += 1

                if django_job.retry_count >= django_job.max_retries:
                    # Reached max retries - mark as final ERROR immediately (no extra pending run)
                    django_job.status = ScraperJobStatus.ERROR
                    django_job.completed_at = current_time

                    log_message = (
                        f"ERROR FINAL (max retries {django_job.max_retries} reached): "
                        f"{error_message or 'Unknown error'}"
                    )
                    self._append_log(django_job, log_message)

                    result["final_status"] = ScraperJobStatus.ERROR
                    result["message"] = f"Max retries reached ({django_job.max_retries}). Job marked as ERROR."

                else:
                    # More retries available - calculate next available_at based on scraper type
                    django_job.status = ScraperJobStatus.PENDING

                    try:
                        scraper_type = ScraperType(django_job.type)
                    except ValueError:
                        # Safe fallback if type is not recognized
                        scraper_type = ScraperType.MONTHLY_REPORTS
                        self._append_log(
                            django_job,
                            f"WARNING: Unknown scraper type '{django_job.type}', using default delay",
                        )

                    django_job.available_at = self._get_retry_available_at(scraper_type)

                    log_message = (
                        f"RETRY SCHEDULED ({django_job.retry_count}/{django_job.max_retries}): "
                        f"{error_message or 'Unknown error'}. "
                        f"Next attempt: {django_job.available_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    self._append_log(django_job, log_message)

                    result["final_status"] = ScraperJobStatus.PENDING
                    result["retry_scheduled"] = True
                    result["retry_count"] = django_job.retry_count
                    result["next_available_at"] = django_job.available_at
                    result["message"] = f"Retry {django_job.retry_count}/{django_job.max_retries} scheduled"

            else:
                # Already at max retries (safety net for jobs in unexpected state)
                django_job.status = ScraperJobStatus.ERROR
                django_job.completed_at = current_time

                log_message = (
                    f"ERROR FINAL (max retries {django_job.max_retries} reached): "
                    f"{error_message or 'Unknown error'}"
                )
                self._append_log(django_job, log_message)

                result["final_status"] = ScraperJobStatus.ERROR
                result["message"] = f"Max retries reached ({django_job.max_retries}). Job marked as ERROR."

        django_job.save()

        if result["final_status"] == ScraperJobStatus.ERROR:
            self._send_error_alert(django_job)

        return result

    def _send_error_alert(self, django_job) -> None:
        """
        Send an error alert email for a failed scraper job.

        Fetches the related context (carrier, client, account) and sends an email
        to all configured recipients in settings.SCRAPER_ALERT_EMAILS.

        Args:
            django_job: The Django ScraperJob instance that reached ERROR status.
        """
        try:
            django_job = DjangoScraperJob.objects.select_related(
                "scraper_config__carrier",
                "scraper_config__account__workspace__client",
            ).get(pk=django_job.pk)

            log_lines = [line.strip() for line in (django_job.log or "").splitlines() if line.strip()]
            error_message = log_lines[-1] if log_lines else "Unknown error"

            mailable = ScraperErrorAlertMailable(
                job_id=django_job.pk,
                scraper_type=django_job.get_type_display(),
                carrier_name=django_job.scraper_config.carrier.name,
                client_name=django_job.scraper_config.account.workspace.client.name,
                account_number=django_job.scraper_config.account.number,
                error_message=error_message,
                retry_count=django_job.retry_count,
                max_retries=django_job.max_retries,
                error_date=django_job.completed_at.strftime("%Y-%m-%d %H:%M UTC") if django_job.completed_at else "N/A",
                logs_url=f"{settings.FRONTEND_URL}/scraper-jobs/{django_job.pk}",
            )

            EmailService(DjangoEmailBackend()).send(mailable)
            logger.info(
                "Scraper error alert sent for job %d (carrier: %s)",
                django_job.pk,
                django_job.scraper_config.carrier.name,
            )
        except Exception:
            logger.exception("Failed to send scraper error alert email for job %d", django_job.pk)

    def _get_retry_available_at(self, scraper_type: ScraperType) -> datetime:
        """
        Calculate the date/time of the next retry based on scraper type.

        Args:
            scraper_type: Type of scraper (MONTHLY_REPORTS, PDF_INVOICE, DAILY_USAGE)

        Returns:
            datetime: Date/time of the next retry

        Delays by type:
            - MONTHLY_REPORTS: 1 day (tomorrow at 6:00 AM)
            - PDF_INVOICE: 1 day (tomorrow at 6:00 AM)
            - DAILY_USAGE: 1 hour from now
        """
        now = timezone.now()
        delay_config = self.RETRY_DELAYS.get(scraper_type, {"days": 1, "hour": 6})

        if "hours" in delay_config:
            # Delay in hours (for DAILY_USAGE)
            return now + timedelta(hours=delay_config["hours"])
        else:
            # Delay in days with specific hour (for MONTHLY_REPORTS and PDF_INVOICE)
            days = delay_config.get("days", 1)
            hour = delay_config.get("hour", 6)
            next_date = now + timedelta(days=days)
            return next_date.replace(hour=hour, minute=0, second=0, microsecond=0)

    def _append_log(self, django_job, message: str, max_message_length: int = 500) -> None:
        """
        Append a message to the job log with timestamp.

        Args:
            django_job: Django ScraperJob model instance
            message: Message to append to the log
            max_message_length: Maximum message length before truncation
        """
        if len(message) > max_message_length:
            message = message[:max_message_length] + "... [truncated]"

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = f"[{timestamp}] {message}"

        if django_job.log:
            django_job.log = f"{django_job.log}\n{new_entry}"
        else:
            django_job.log = new_entry

    def get_job_retry_info(self, scraper_job_id: int) -> Dict[str, Any]:
        """
        Get information about the retry status of a job.

        Args:
            scraper_job_id: Job ID

        Returns:
            Dict with retry information:
            {
                'job_id': int,
                'retry_count': int,
                'max_retries': int,
                'retries_remaining': int,
                'can_retry': bool,
                'status': str
            }
        """
        django_job = DjangoScraperJob.objects.get(id=scraper_job_id)

        return {
            "job_id": scraper_job_id,
            "retry_count": django_job.retry_count,
            "max_retries": django_job.max_retries,
            "retries_remaining": max(0, django_job.max_retries - django_job.retry_count),
            "can_retry": django_job.retry_count < django_job.max_retries,
            "status": django_job.status,
        }
