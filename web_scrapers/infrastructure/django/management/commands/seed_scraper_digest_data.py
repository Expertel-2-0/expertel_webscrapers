"""
Management command: seed_scraper_digest_data

Creates a minimal but realistic set of fixtures in the shared database so
that ``send_scraper_digest --dry-run`` (and unit tests) can exercise every
section of the daily digest email without needing live scraper data.

SAFETY GUARD
------------
This command writes to the configured database.  If that database is not a
local development instance, the guard at the top of ``handle()`` will abort
unless ``--force`` is explicitly passed.

All created objects are identifiable by the ``DIGEST-TEST-`` prefix in their
name / number fields.  Use ``--clean`` to remove them in safe reverse-FK order.

Usage
-----
    python manage.py seed_scraper_digest_data            # local guard check
    python manage.py seed_scraper_digest_data --clean    # remove test data
    python manage.py seed_scraper_digest_data --force    # skip guard
"""

from __future__ import annotations

import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from web_scrapers.infrastructure.django.enums import (
    BillingCycleStatusChoices,
    FileStatusChoices,
    ScraperJobStatus,
    ScraperType,
)
from web_scrapers.infrastructure.django.models import (
    Account,
    BillingCycle,
    BillingCycleFile,
    Carrier,
    CarrierPortalCredential,
    CarrierReport,
    Client,
    ScraperConfig,
    ScraperJob,
    Workspace,
)

PREFIX = "DIGEST-TEST-"


class Command(BaseCommand):
    """
    Seed the database with scraper digest test fixtures.

    All created records use the ``DIGEST-TEST-`` prefix so they can be
    identified and removed cleanly with ``--clean``.

    SAFETY GUARD: aborts unless ENVIRONMENT=local or --force is passed.
    """

    help = (
        "Seed test fixtures for the daily scraper health digest.  "
        "Only runs against local databases (ENVIRONMENT=local) unless --force is given."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--clean",
            action="store_true",
            default=False,
            help="Delete all DIGEST-TEST-* objects and exit.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Skip the ENVIRONMENT=local safety guard (dangerous on production).",
        )

    # ------------------------------------------------------------------
    # Safety guard
    # ------------------------------------------------------------------

    def _safety_guard(self, force: bool) -> None:
        """Abort if the configured database is not local, unless --force is passed."""
        environment = os.environ.get("ENVIRONMENT", "")
        if environment == "local" or force:
            return

        db_host = os.environ.get("DB_HOST", "<unknown>")
        raise CommandError(
            f"Safety guard: ENVIRONMENT is '{environment}' (not 'local') and "
            f"--force was not passed.  "
            f"Configured DB_HOST is '{db_host}'.  "
            f"Run with --force to override (dangerous on production)."
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _clean(self) -> None:
        """Remove all DIGEST-TEST-* objects in reverse FK dependency order."""
        self.stdout.write("Cleaning DIGEST-TEST-* fixtures...")

        # Jobs
        deleted, _ = ScraperJob.objects.filter(scraper_config__carrier__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} ScraperJob(s)")

        # BillingCycleFiles
        deleted, _ = BillingCycleFile.objects.filter(carrier_report__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} BillingCycleFile(s)")

        # CarrierReports
        deleted, _ = CarrierReport.objects.filter(name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} CarrierReport(s)")

        # BillingCycles
        deleted, _ = BillingCycle.objects.filter(account__workspace__client__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} BillingCycle(s)")

        # ScraperConfigs
        deleted, _ = ScraperConfig.objects.filter(carrier__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} ScraperConfig(s)")

        # Accounts
        deleted, _ = Account.objects.filter(workspace__client__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} Account(s)")

        # Workspaces
        deleted, _ = Workspace.objects.filter(client__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} Workspace(s)")

        # CarrierPortalCredentials
        deleted, _ = CarrierPortalCredential.objects.filter(client__name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} CarrierPortalCredential(s)")

        # Carriers
        deleted, _ = Carrier.objects.filter(name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} Carrier(s)")

        # Clients
        deleted, _ = Client.objects.filter(name__startswith=PREFIX).delete()
        self.stdout.write(f"  Deleted {deleted} Client(s)")

        self.stdout.write(self.style.SUCCESS("Clean complete."))

    # ------------------------------------------------------------------
    # Seed helpers
    # ------------------------------------------------------------------

    def _get_or_create_client(self, suffix: str) -> Client:
        client, created = Client.objects.get_or_create(
            name=f"{PREFIX}Client-{suffix}",
            defaults={
                "zip_code": "00000",
                "phone_number": "555-0000",
            },
        )
        if created:
            self.stdout.write(f"  Created Client: {client.name}")
        return client

    def _get_or_create_carrier(self, suffix: str) -> Carrier:
        carrier, created = Carrier.objects.get_or_create(
            name=f"{PREFIX}{suffix}",
        )
        if created:
            self.stdout.write(f"  Created Carrier: {carrier.name}")
        return carrier

    def _get_or_create_workspace(self, client: Client, suffix: str) -> Workspace:
        workspace, created = Workspace.objects.get_or_create(
            name=f"{PREFIX}Workspace-{suffix}",
            client=client,
        )
        if created:
            self.stdout.write(f"  Created Workspace: {workspace.name}")
        return workspace

    def _get_or_create_account(self, workspace: Workspace, carrier: Carrier, suffix: str) -> Account:
        account, created = Account.objects.get_or_create(
            number=f"{PREFIX}Acct-{suffix}",
            workspace=workspace,
            carrier=carrier,
        )
        if created:
            self.stdout.write(f"  Created Account: {account.number}")
        return account

    def _get_or_create_credential(self, client: Client, carrier: Carrier, suffix: str) -> CarrierPortalCredential:
        cred, created = CarrierPortalCredential.objects.get_or_create(
            username=f"{PREFIX}user-{suffix}",
            client=client,
            carrier=carrier,
            defaults={"password": f"{PREFIX}pass-{suffix}"},
        )
        if created:
            self.stdout.write(f"  Created CarrierPortalCredential: {cred.username}")
        return cred

    def _get_or_create_scraper_config(
        self,
        account: Account,
        credential: CarrierPortalCredential,
        carrier: Carrier,
    ) -> ScraperConfig:
        config, created = ScraperConfig.objects.get_or_create(
            account=account,
            defaults={"credential": credential, "carrier": carrier},
        )
        if created:
            self.stdout.write(f"  Created ScraperConfig for account: {account.number}")
        return config

    def _create_billing_cycle(self, account: Account, days_ago: int) -> BillingCycle:
        now = timezone.now()
        start = (now - timedelta(days=days_ago + 30)).date()
        end = (now - timedelta(days=days_ago)).date()
        cycle = BillingCycle.objects.create(
            start_date=start,
            end_date=end,
            account=account,
            status=BillingCycleStatusChoices.OPEN,
        )
        self.stdout.write(f"  Created BillingCycle {cycle.id} for account {account.number}")
        return cycle

    def _create_error_job(
        self,
        config: ScraperConfig,
        cycle: BillingCycle,
        job_type: str,
        hours_ago: float,
        log: str,
    ) -> ScraperJob:
        now = timezone.now()
        job = ScraperJob.objects.create(
            billing_cycle=cycle,
            scraper_config=config,
            status=ScraperJobStatus.ERROR,
            type=job_type,
            log=log,
            completed_at=now - timedelta(hours=hours_ago),
            available_at=now - timedelta(hours=hours_ago + 1),
            retry_count=3,
            max_retries=3,
        )
        self.stdout.write(f"  Created error ScraperJob {job.id} ({job_type}, {hours_ago}h ago)")
        return job

    def _create_success_job(
        self,
        config: ScraperConfig,
        cycle: BillingCycle,
        job_type: str,
        hours_ago: float,
        retry_count: int = 0,
    ) -> ScraperJob:
        now = timezone.now()
        job = ScraperJob.objects.create(
            billing_cycle=cycle,
            scraper_config=config,
            status=ScraperJobStatus.SUCCESS,
            type=job_type,
            completed_at=now - timedelta(hours=hours_ago),
            available_at=now - timedelta(hours=hours_ago + 1),
            retry_count=retry_count,
            max_retries=3,
        )
        self.stdout.write(f"  Created success ScraperJob {job.id} ({job_type}, {hours_ago}h ago)")
        return job

    # ------------------------------------------------------------------
    # Main handle
    # ------------------------------------------------------------------

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        force: bool = options["force"]
        clean: bool = options["clean"]

        self._safety_guard(force)

        if clean:
            self._clean()
            return

        now = timezone.now()

        with transaction.atomic():
            self._seed(now)

        self.stdout.write(self.style.SUCCESS("Seed complete.  Use --clean to remove all DIGEST-TEST-* objects."))

    def _seed(self, now) -> None:  # type: ignore[no-untyped-def]
        """Create all test fixtures inside a single transaction."""

        # ── Celda A: Verizon / monthly_reports — 2 HIGH errors ───────────────
        self.stdout.write("\n--- Cell A: DIGEST-TEST-Verizon / monthly_reports (HIGH errors) ---")
        carrier_vz = self._get_or_create_carrier("Verizon")
        client_vz = self._get_or_create_client("Verizon")
        ws_vz = self._get_or_create_workspace(client_vz, "Verizon")
        acct_vz = self._get_or_create_account(ws_vz, carrier_vz, "VZ-001")
        cred_vz = self._get_or_create_credential(client_vz, carrier_vz, "VZ")
        config_vz = self._get_or_create_scraper_config(acct_vz, cred_vz, carrier_vz)
        cycle_vz1 = self._create_billing_cycle(acct_vz, days_ago=1)
        cycle_vz2 = self._create_billing_cycle(acct_vz, days_ago=2)

        high_log_1 = (
            "INFO Starting Verizon monthly reports scraper\n"
            "INFO Navigating to reports portal\n"
            "INFO Waiting for 'My Reports' button\n"
            "ERROR Timeout waiting for element: 'My Reports' button not found after 30s\n"
            "ERROR Selector '.reports-nav-btn' did not appear within the expected window\n"
            "ERROR Scraper exited with unrecoverable error — portal layout may have changed"
        )
        # Pad to >600 chars to satisfy seed spec
        high_log_1 = high_log_1.ljust(650, " ")

        high_log_2 = (
            "INFO Verizon monthly reports — downloading billing package\n"
            "INFO Download completed: billing_2026_05.zip (2.4 MB)\n"
            "INFO Extracting ZIP archive to temp directory\n"
            "ERROR Error extracting ZIP: file is corrupted or truncated\n"
            "ERROR zipfile.BadZipFile: File is not a zip file\n"
            "ERROR Failed to process downloaded archive — manual intervention required"
        )
        high_log_2 = high_log_2.ljust(650, " ")

        self._create_error_job(config_vz, cycle_vz1, ScraperType.MONTHLY_REPORTS, 2.0, high_log_1)
        self._create_error_job(config_vz, cycle_vz2, ScraperType.MONTHLY_REPORTS, 5.0, high_log_2)

        # ── Celda B: Bell / daily_usage — 2 LOW errors ────────────────────────
        self.stdout.write("\n--- Cell B: DIGEST-TEST-Bell / daily_usage (LOW errors) ---")
        carrier_bell = self._get_or_create_carrier("Bell")
        client_bell = self._get_or_create_client("Bell")
        ws_bell = self._get_or_create_workspace(client_bell, "Bell")
        acct_bell = self._get_or_create_account(ws_bell, carrier_bell, "BELL-001")
        cred_bell = self._get_or_create_credential(client_bell, carrier_bell, "Bell")
        config_bell = self._get_or_create_scraper_config(acct_bell, cred_bell, carrier_bell)
        cycle_bell1 = self._create_billing_cycle(acct_bell, days_ago=1)
        cycle_bell2 = self._create_billing_cycle(acct_bell, days_ago=2)

        low_log_1 = (
            "INFO Bell daily usage scraper starting\n"
            "INFO Navigating to Bell MyBusiness portal\n"
            "INFO Entering credentials for account BELL-001\n"
            "WARNING Login failed for Carrier.BELL — username or password incorrect\n"
            "ERROR Authentication rejected by portal — credentials may have been rotated\n"
            "ERROR Scraper aborted: could not authenticate after 3 attempts"
        )
        low_log_2 = (
            "INFO Bell daily usage scraper starting\n"
            "INFO Navigating to Bell MyBusiness portal\n"
            "INFO Credentials accepted, proceeding to 2FA challenge\n"
            "WARNING CAPTCHA failed after two attempts — CAPTCHA image not recognized\n"
            "ERROR Unable to complete CAPTCHA challenge — may require human intervention\n"
            "ERROR Authentication blocked: CAPTCHA not solved"
        )
        self._create_error_job(config_bell, cycle_bell1, ScraperType.DAILY_USAGE, 1.5, low_log_1)
        self._create_error_job(config_bell, cycle_bell2, ScraperType.DAILY_USAGE, 3.0, low_log_2)

        # ── Zombies ────────────────────────────────────────────────────────────
        self.stdout.write("\n--- Zombies ---")
        cycle_zombie_vz = self._create_billing_cycle(acct_vz, days_ago=3)
        cycle_zombie_bell = self._create_billing_cycle(acct_bell, days_ago=3)

        zombie1 = ScraperJob.objects.create(
            billing_cycle=cycle_zombie_vz,
            scraper_config=config_vz,
            status=ScraperJobStatus.IN_PROGRESS,
            type=ScraperType.MONTHLY_REPORTS,
            available_at=now - timedelta(hours=8),
            retry_count=1,
            max_retries=3,
        )
        self.stdout.write(f"  Created zombie (in_progress, 8h ago): job {zombie1.id}")

        zombie2 = ScraperJob.objects.create(
            billing_cycle=cycle_zombie_bell,
            scraper_config=config_bell,
            status=ScraperJobStatus.RUNNING,
            type=ScraperType.DAILY_USAGE,
            available_at=None,
            retry_count=0,
            max_retries=3,
        )
        self.stdout.write(f"  Created zombie (running, available_at=NULL): job {zombie2.id}")

        # ── Silent gap: monthly_reports success with unprocessed files ─────────
        self.stdout.write("\n--- Silent gap: monthly_reports success with mixed file statuses ---")
        cycle_gap = self._create_billing_cycle(acct_vz, days_ago=0)

        carrier_report_processed = CarrierReport.objects.create(
            name=f"{PREFIX}Report-Processed",
            carrier=carrier_vz,
            slug="digest-test-processed",
        )
        carrier_report_error = CarrierReport.objects.create(
            name=f"{PREFIX}Report-Error",
            carrier=carrier_vz,
            slug="digest-test-error",
        )
        carrier_report_to_fetch = CarrierReport.objects.create(
            name=f"{PREFIX}Report-ToFetch",
            carrier=carrier_vz,
            slug="digest-test-to-fetch",
        )
        self.stdout.write(f"  Created CarrierReport(s): processed / error / to_be_fetched")

        BillingCycleFile.objects.create(
            billing_cycle=cycle_gap,
            carrier_report=carrier_report_processed,
            status=FileStatusChoices.PROCESSED,
        )
        BillingCycleFile.objects.create(
            billing_cycle=cycle_gap,
            carrier_report=carrier_report_error,
            status=FileStatusChoices.ERROR,
        )
        BillingCycleFile.objects.create(
            billing_cycle=cycle_gap,
            carrier_report=carrier_report_to_fetch,
            status=FileStatusChoices.TO_BE_FETCHED,
        )
        self.stdout.write("  Created 3 BillingCycleFile(s): processed / error / to_be_fetched")

        gap_job = ScraperJob.objects.create(
            billing_cycle=cycle_gap,
            scraper_config=config_vz,
            status=ScraperJobStatus.SUCCESS,
            type=ScraperType.MONTHLY_REPORTS,
            completed_at=now - timedelta(hours=1),
            available_at=now - timedelta(hours=2),
            retry_count=0,
            max_retries=3,
        )
        self.stdout.write(f"  Created silent-gap ScraperJob {gap_job.id}")

        # ── ~10 success jobs spread over last 7 days (health context + run rate) ─
        self.stdout.write("\n--- Health context / run-rate background jobs ---")
        success_schedule = [
            # (config, job_type, hours_ago, retry_count)
            (config_vz, ScraperType.MONTHLY_REPORTS, 6, 0),
            (config_vz, ScraperType.MONTHLY_REPORTS, 30, 1),
            (config_vz, ScraperType.MONTHLY_REPORTS, 54, 0),
            (config_vz, ScraperType.MONTHLY_REPORTS, 78, 2),
            (config_bell, ScraperType.DAILY_USAGE, 12, 0),
            (config_bell, ScraperType.DAILY_USAGE, 36, 1),
            (config_bell, ScraperType.DAILY_USAGE, 60, 0),
            (config_bell, ScraperType.DAILY_USAGE, 84, 0),
            (config_vz, ScraperType.PDF_INVOICE, 18, 0),
            (config_bell, ScraperType.MONTHLY_REPORTS, 42, 0),
        ]

        for cfg, jtype, hours_ago, retries in success_schedule:
            cycle = self._create_billing_cycle(cfg.account, days_ago=max(1, hours_ago // 24 + 1))
            self._create_success_job(cfg, cycle, jtype, hours_ago, retry_count=retries)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "All fixtures created.  Run 'python manage.py send_scraper_digest --dry-run' " "to preview the digest."
            )
        )
