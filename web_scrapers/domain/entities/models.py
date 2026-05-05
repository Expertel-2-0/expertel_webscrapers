import base64
from datetime import date, datetime
from typing import List, Optional

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, field_validator

from django.conf import settings

from web_scrapers.domain.enums import AccountType, BillingCycleStatus, FileStatus, ScraperJobStatus, ScraperType

SECRET_KEY = settings.ENCRYPTION_KEY.encode()
cipher = Fernet(SECRET_KEY)


class FileDownloadInfo(BaseModel):
    """Information about a file downloaded by a scraper."""

    file_id: int
    file_name: str
    download_url: str
    file_path: str
    download_timestamp: Optional[datetime] = None
    billing_cycle_file: Optional["BillingCycleFile"] = None  # Mapping to corresponding BillingCycleFile
    daily_usage_file: Optional["BillingCycleDailyUsageFile"] = (
        None  # Mapping to corresponding BillingCycleDailyUsageFile
    )
    pdf_file: Optional["BillingCyclePDFFile"] = None  # Mapping to corresponding BillingCyclePDFFile

    model_config = {"from_attributes": True}


class Client(BaseModel):
    id: Optional[int] = None
    name: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: str
    phone_number: str
    related_collection: Optional[str] = None
    is_trial: bool = False
    trial_ends: Optional[datetime] = None
    active: bool = True
    managed_by_expertel: bool = True

    model_config = {"from_attributes": True}


class Workspace(BaseModel):
    id: Optional[int] = None
    name: str
    client_id: int
    client: Optional["Client"] = None

    model_config = {"from_attributes": True}


class Carrier(BaseModel):
    id: Optional[int] = None
    name: str
    logo: Optional[str] = None
    metadata: Optional[dict] = None

    model_config = {"from_attributes": True}


class Account(BaseModel):
    id: Optional[int] = None
    number: str
    nickname: Optional[str] = None
    workspace_id: int
    carrier_id: int
    account_type: AccountType = AccountType.CORPORATE
    billing_day: int = 15
    description: Optional[str] = None
    workspace: Optional["Workspace"] = None
    carrier: Optional["Carrier"] = None

    model_config = {"from_attributes": True}

    @field_validator("billing_day", mode="before")
    @classmethod
    def _default_billing_day_when_invalid(cls, value):
        if isinstance(value, int) and 1 <= value <= 31:
            return value
        return 15


class BillingCycle(BaseModel):
    id: Optional[int] = None
    start_date: date
    end_date: date
    account_id: int
    status: BillingCycleStatus = BillingCycleStatus.OPEN
    account: Optional["Account"] = None
    billing_cycle_files: Optional[List["BillingCycleFile"]] = []
    daily_usage_files: Optional[List["BillingCycleDailyUsageFile"]] = []
    pdf_files: Optional[List["BillingCyclePDFFile"]] = []
    scraper_jobs: Optional[List["ScraperJob"]] = []

    model_config = {"from_attributes": True}


class CarrierReport(BaseModel):
    id: Optional[int] = None
    name: str
    carrier_id: int
    slug: Optional[str] = None
    details: Optional[dict] = None
    required: Optional[bool] = False

    model_config = {"from_attributes": True}


class BillingCycleFile(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: int
    carrier_report_id: int
    status: FileStatus = FileStatus.TO_BE_FETCHED
    status_comment: Optional[str] = None
    s3_key: Optional[str] = None
    carrier_report: Optional["CarrierReport"] = None

    model_config = {"from_attributes": True}


class CarrierPortalCredential(BaseModel):
    id: Optional[int] = None
    username: str
    password: str
    client_id: int
    carrier_id: int
    nickname: Optional[str] = None

    model_config = {"from_attributes": True}

    def get_decrypted_password(self) -> str:
        """Decrypt and return the password."""
        decrypted = cipher.decrypt(base64.urlsafe_b64decode(self.password.encode()))
        return decrypted.decode()


class BillingCycleDailyUsageFile(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: int
    status: FileStatus = FileStatus.TO_BE_FETCHED
    s3_key: Optional[str] = None

    model_config = {"from_attributes": True}


class BillingCyclePDFFile(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: int
    status: FileStatus = FileStatus.TO_BE_FETCHED
    status_comment: Optional[str] = None
    s3_key: Optional[str] = None
    pdf_type: Optional[str] = None  # 'invoice', 'statement', etc.

    model_config = {"from_attributes": True}


class ScraperConfig(BaseModel):
    id: Optional[int] = None
    account_id: int
    credential_id: int
    carrier_id: int
    parameters: Optional[dict] = None
    days_offset: int = 0

    model_config = {"from_attributes": True}


class ScraperJob(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: int
    scraper_config_id: int
    status: ScraperJobStatus = ScraperJobStatus.PENDING
    type: ScraperType = ScraperType.DAILY_USAGE
    log: Optional[str] = None
    completed_at: Optional[datetime] = None
    available_at: Optional[datetime] = None
    retry_count: int = 0  # Number of retry attempts performed
    max_retries: int = 3  # Maximum retry attempts allowed

    model_config = {"from_attributes": True}

    def can_retry(self) -> bool:
        """Check if the job can be retried."""
        return self.retry_count < self.max_retries

    def retries_remaining(self) -> int:
        """Return the number of retries remaining."""
        return max(0, self.max_retries - self.retry_count)


# Filters for each entity
class ClientFilter(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    contact_email: Optional[str] = None
    zip_code: Optional[str] = None
    phone_number: Optional[str] = None
    related_collection: Optional[str] = None
    is_testing: Optional[bool] = None
    trial_ends: Optional[datetime] = None
    active: Optional[bool] = None
    managed_by_expertel: Optional[bool] = None

    model_config = {"from_attributes": True}


class WorkspaceFilter(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    client_id: Optional[int] = None

    model_config = {"from_attributes": True}


class CarrierFilter(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    metadata: Optional[dict] = None

    model_config = {"from_attributes": True}


class AccountFilter(BaseModel):
    id: Optional[int] = None
    number: Optional[str] = None
    nickname: Optional[str] = None
    workspace_id: Optional[int] = None
    carrier_id: Optional[int] = None
    billing_day: Optional[int] = None
    description: Optional[str] = None
    ids: Optional[list[int]] = None

    model_config = {"from_attributes": True}


class BillingCycleFilter(BaseModel):
    id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    account_id: Optional[int] = None
    status: Optional[BillingCycleStatus] = None
    ids: Optional[list[int]] = None

    model_config = {"from_attributes": True}


class BillingCycleFileFilter(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: Optional[int] = None
    carrier_report_id: Optional[int] = None
    status: Optional[FileStatus] = None
    status_comment: Optional[str] = None

    model_config = {"from_attributes": True}


class CarrierPortalCredentialFilter(BaseModel):
    id: Optional[int] = None
    client_id: Optional[int] = None
    carrier_id: Optional[int] = None

    model_config = {"from_attributes": True}


class ScraperConfigFilter(BaseModel):
    id: Optional[int] = None
    account_id: Optional[int] = None
    credential_id: Optional[int] = None
    carrier_id: Optional[int] = None
    days_offset: Optional[int] = None

    model_config = {"from_attributes": True}


class ScraperJobFilter(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: Optional[int] = None
    scraper_config_id: Optional[int] = None
    status: Optional[ScraperJobStatus] = None
    type: Optional[ScraperType] = None
    completed_at: Optional[datetime] = None
    available_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BillingCycleDailyUsageFileFilter(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: Optional[int] = None
    status: Optional[FileStatus] = None
    s3_key: Optional[str] = None

    model_config = {"from_attributes": True}


class BillingCyclePDFFileFilter(BaseModel):
    id: Optional[int] = None
    billing_cycle_id: Optional[int] = None
    status: Optional[FileStatus] = None
    status_comment: Optional[str] = None
    pdf_type: Optional[str] = None

    model_config = {"from_attributes": True}


# Service Response Models
class ScraperJobCompleteContext(BaseModel):
    """Complete context for a scraper job execution"""

    scraper_job: ScraperJob
    scraper_config: ScraperConfig
    billing_cycle: BillingCycle  # Complete with all files assembled
    credential: CarrierPortalCredential
    account: Account
    carrier: Carrier
    workspace: Workspace
    client: Client

    model_config = {"from_attributes": True}


class ScraperStatistics(BaseModel):
    """Statistics about scraper jobs status"""

    timestamp: datetime
    total_pending: int
    available_now: int
    future_scheduled: int
    null_available_at: int
    in_progress: int = 0  # Jobs claimed but not yet running
    running: int = 0  # Jobs currently being executed

    model_config = {"from_attributes": True}


class FileMappingInfo(BaseModel):
    """File mapping information for API endpoints"""

    file_id: int
    file_name: str
    file_path: str
    download_url: str
    billing_cycle_file_id: Optional[int] = None
    carrier_report_name: Optional[str] = None
    daily_usage_file_id: Optional[int] = None
    pdf_file_id: Optional[int] = None

    model_config = {"from_attributes": True}
