import logging
import os
import shutil
import traceback
import uuid
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import (
    BillingCycle,
    BillingCycleDailyUsageFile,
    BillingCycleFile,
    FileDownloadInfo,
    FileMappingInfo,
    ScraperConfig,
)
from web_scrapers.domain.entities.session import Credentials
from web_scrapers.infrastructure.services.file_upload_service import FileUploadService


class ScraperResult:
    def __init__(
        self,
        success: bool,
        message: str = "",
        files: Optional[List[FileMappingInfo]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.message = message
        self.files = files or []
        self.error = error
        self.timestamp = datetime.now()


class ScraperBaseStrategy(ABC):
    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        self.browser_wrapper = browser_wrapper
        self.job_id = job_id
        self.job_downloads_dir: Optional[str] = None
        # In-flight warnings the orchestrator should persist to the job's stored
        # log after execute() returns. Plain self.logger.warning() only reaches
        # the file/console handler; entries appended here also reach the DB log
        # via main.py -> ScraperJobService.append_job_log.
        self.job_warnings: List[str] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def _record_job_warning(self, message: str) -> None:
        """Log a warning at WARNING level and queue it for the job's stored log.

        Use this for anomalies that don't necessarily fail execution but matter
        when reviewing a job after the fact — e.g. the page is not on the
        expected state, an upstream value reads as zero, etc.
        """
        self.logger.warning(message)
        self.job_warnings.append(message)

    @abstractmethod
    def execute(self, config: ScraperConfig, billing_cycle: BillingCycle, credentials: Credentials) -> ScraperResult:
        raise NotImplementedError()

    def _prepare_job_directory(self) -> str:
        downloads_base = os.path.abspath("downloads")
        job_dir = os.path.join(downloads_base, f"job_{self.job_id}")

        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
            self.logger.info(f"Cleaned existing directory for job_{self.job_id}")

        os.makedirs(job_dir, exist_ok=True)
        self.job_downloads_dir = job_dir
        self.logger.info(f"Prepared download directory: {job_dir}")
        return job_dir

    def _cleanup_job_directory(self) -> None:
        if os.path.exists(self.job_downloads_dir):
            shutil.rmtree(self.job_downloads_dir)
            self.logger.info(f"Folder job_{self.job_id} deleted after complete success")

    def _create_file_mapping(self, downloaded_files: List[FileDownloadInfo]) -> List[FileMappingInfo]:
        """Convert FileDownloadInfo to mapping format required for endpoints."""
        return [
            FileMappingInfo(
                file_id=file_info.file_id,
                file_name=file_info.file_name,
                file_path=file_info.file_path,
                download_url=file_info.download_url,
                billing_cycle_file_id=file_info.billing_cycle_file.id if file_info.billing_cycle_file else None,
                carrier_report_name=(
                    file_info.billing_cycle_file.carrier_report.name
                    if (file_info.billing_cycle_file and file_info.billing_cycle_file.carrier_report)
                    else None
                ),
                daily_usage_file_id=file_info.daily_usage_file.id if file_info.daily_usage_file else None,
                pdf_file_id=file_info.pdf_file.id if file_info.pdf_file else None,
            )
            for file_info in downloaded_files
        ]

    def _extract_zip_files(self, zip_file_path: str, extract_to_dir: Optional[str] = None) -> List[str]:
        """
        Extract files from a ZIP and return paths of all extracted files.

        Args:
            zip_file_path: Path of the ZIP file to extract
            extract_to_dir: Directory to extract to (if not specified, uses ZIP directory)

        Returns:
            List of extracted file paths
        """
        extracted_files = []
        try:
            # Verify that file exists and is a ZIP
            if not os.path.exists(zip_file_path):
                self.logger.error(f"ZIP file not found: {zip_file_path}")
                return extracted_files

            if not zipfile.is_zipfile(zip_file_path):
                self.logger.error(f"File is not a valid ZIP: {zip_file_path}")
                return extracted_files

            # Determine extraction directory with unique UUID
            if extract_to_dir is None:
                zip_basename = os.path.splitext(os.path.basename(zip_file_path))[0]
                unique_id = str(uuid.uuid4())[:8]  # Use only first 8 characters of UUID
                extract_to_dir = os.path.join(os.path.dirname(zip_file_path), f"{zip_basename}_extracted_{unique_id}")

            # Create extraction directory if it doesn't exist
            os.makedirs(extract_to_dir, exist_ok=True)

            self.logger.info(f"Extracting ZIP: {os.path.basename(zip_file_path)}")
            self.logger.info(f"Extraction directory: {extract_to_dir}")

            # Extract files
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                file_list = zip_ref.namelist()
                self.logger.info(f"Elements in ZIP: {len(file_list)}")

                for file_name in file_list:
                    # Only process files, not directories
                    if not file_name.endswith("/"):
                        # Get only the filename (without folder path)
                        base_filename = os.path.basename(file_name)

                        # Avoid hidden or system files
                        if base_filename and not base_filename.startswith("."):
                            # Read file content from ZIP
                            file_content = zip_ref.read(file_name)

                            # Create destination path at first level
                            flattened_file_path = os.path.join(extract_to_dir, base_filename)

                            # If file with same name exists, add a number
                            counter = 1
                            original_path = flattened_file_path
                            while os.path.exists(flattened_file_path):
                                name, ext = os.path.splitext(base_filename)
                                flattened_file_path = os.path.join(extract_to_dir, f"{name}_{counter}{ext}")
                                counter += 1

                            # Write file to extraction directory (first level)
                            with open(flattened_file_path, "wb") as output_file:
                                output_file.write(file_content)

                            extracted_files.append(flattened_file_path)

                            # Show extraction information
                            if file_name != base_filename:
                                self.logger.debug(f"Extracted: {file_name} -> {base_filename}")
                            else:
                                self.logger.debug(f"Extracted: {base_filename}")
                        else:
                            self.logger.debug(f"Ignored system file: {file_name}")
                    else:
                        self.logger.debug(f"Ignored directory: {file_name}")

            # Extraction summary
            self.logger.info(f"EXTRACTION SUMMARY:")
            self.logger.info(f"Total files extracted: {len(extracted_files)}")

            if len(extracted_files) == 1:
                self.logger.info(f"Single file: {os.path.basename(extracted_files[0])}")
            else:
                self.logger.info(f"Multiple files:")
                for i, file_path in enumerate(extracted_files, 1):
                    self.logger.debug(f"     [{i}] {os.path.basename(file_path)}")

            self.logger.info("===============================")

            return extracted_files

        except Exception as e:
            self.logger.error(f"Error extracting ZIP: {str(e)}")
            return extracted_files

    def _upload_files_to_endpoint(
        self, files: List[FileDownloadInfo], config: ScraperConfig, billing_cycle: BillingCycle
    ) -> bool:
        """Base method to send files to endpoint. Override if you need specific logic."""
        try:
            upload_service = FileUploadService()

            # Determine upload type based on class
            upload_type = self._get_upload_type()

            return upload_service.upload_files_batch(
                files=files, billing_cycle=billing_cycle, upload_type=upload_type, additional_data=None
            )

        except Exception as e:
            self.logger.error(f"Error uploading files: {str(e)}")
            return False

    def _upload_files_with_individual_tracking(
        self, files: List[FileDownloadInfo], config: ScraperConfig, billing_cycle: BillingCycle
    ) -> Dict[str, Any]:
        """
        Upload files with individual tracking for each file.

        Returns a dictionary with detailed results:
        {
            'total_files': int,
            'successful_uploads': int,
            'failed_uploads': int,
            'success': bool,
            'uploaded_files': List[FileDownloadInfo],
            'failed_files': List[Dict[str, Any]]
        }
        """
        upload_service = FileUploadService()
        upload_type = self._get_upload_type()

        uploaded_files = []
        failed_files = []

        self.logger.info(f"Starting individual upload tracking for {len(files)} files...")

        for file_info in files:
            try:
                # Verify file exists and has a physical path
                if not file_info.file_path or not os.path.exists(file_info.file_path):
                    self.logger.warning(f"File not found on disk: {file_info.file_name}")
                    failed_files.append(
                        {"file": file_info, "reason": "File not found on disk", "file_path": file_info.file_path}
                    )
                    continue

                # Attempt to upload this single file
                self.logger.info(f"Uploading: {file_info.file_name}")
                success = upload_service.upload_files_batch(
                    files=[file_info], billing_cycle=billing_cycle, upload_type=upload_type, additional_data=None
                )

                if success:
                    self.logger.info(f"Upload successful: {file_info.file_name}")
                    uploaded_files.append(file_info)
                else:
                    self.logger.error(f"Upload failed: {file_info.file_name}")
                    failed_files.append(
                        {
                            "file": file_info,
                            "reason": "Upload service returned failure",
                            "file_path": file_info.file_path,
                        }
                    )

            except Exception as e:
                self.logger.error(f"Exception uploading {file_info.file_name}: {str(e)}")
                failed_files.append(
                    {"file": file_info, "reason": f"Exception: {str(e)}", "file_path": file_info.file_path}
                )

        # Build result summary
        result = {
            "total_files": len(files),
            "successful_uploads": len(uploaded_files),
            "failed_uploads": len(failed_files),
            "success": len(failed_files) == 0,  # Only success if ALL uploaded
            "uploaded_files": uploaded_files,
            "failed_files": failed_files,
        }

        # Log summary
        self.logger.info(
            f"Upload tracking complete: {result['successful_uploads']}/{result['total_files']} successful"
        )

        return result

    def _get_upload_type(self) -> str:
        """Determine upload type based on strategy class."""
        class_name = self.__class__.__name__.lower()
        if "monthly" in class_name:
            return "monthly"
        elif "daily" in class_name:
            return "daily_usage"
        elif "pdf" in class_name:
            return "pdf_invoice"
        else:
            return "unknown"


class MonthlyReportsScraperStrategy(ScraperBaseStrategy):

    def execute(self, config: ScraperConfig, billing_cycle: BillingCycle, credentials: Credentials) -> ScraperResult:
        try:
            # Step 0: Prepare job directory
            self._prepare_job_directory()

            # Step 1: Find files section
            files_section = self._find_files_section(config, billing_cycle)
            if not files_section:
                return ScraperResult(False, error="Could not find files section")

            # Step 2: Download files
            # Snapshot which files already have s3_key BEFORE downloading — some scrapers skip
            # those files intentionally (they were uploaded in a prior run). Counting them as
            # "failed to download" would produce false-negative job results.
            all_cycle_files: list[BillingCycleFile] = billing_cycle.billing_cycle_files or []

            # Only REQUIRED reports count toward failure. Some CarrierReport rows are optional
            # (required=False) because a portal doesn't reliably offer them yet (e.g. Bell "dtl",
            # Telus "airtime_detail", Verizon "wireless_usage_detail") — the scraper deliberately
            # doesn't fetch them. A missing optional report is expected, not an error.
            # required is nullable in the DB; treat None the same as False (optional).
            required_cycle_files = [f for f in all_cycle_files if f.carrier_report and f.carrier_report.required]
            optional_cycle_files = [f for f in all_cycle_files if not (f.carrier_report and f.carrier_report.required)]

            already_with_s3 = sum(1 for f in required_cycle_files if f.s3_key)

            downloaded_files = self._download_files(files_section, config, billing_cycle)

            # Calculate expected files from billing_cycle (required only)
            expected_files_count = len(required_cycle_files)
            downloaded_count = len(downloaded_files)
            required_downloaded_count = sum(
                1
                for f in downloaded_files
                if f.billing_cycle_file
                and f.billing_cycle_file.carrier_report
                and f.billing_cycle_file.carrier_report.required
            )
            # A file may be counted twice: already in S3 from a prior run AND re-downloaded
            # this run (e.g. Rogers always re-fetches the BCR even when it already exists).
            # Cap at the expected total so double-counting can't push failures negative.
            effective_count = min(expected_files_count, required_downloaded_count + already_with_s3)

            optional_missing = [
                f.carrier_report.slug or f.carrier_report.name
                for f in optional_cycle_files
                if not f.s3_key
                and not any(d.billing_cycle_file and d.billing_cycle_file.id == f.id for d in downloaded_files)
            ]
            if optional_missing:
                self.logger.info(f"Optional report(s) not available this cycle: {', '.join(optional_missing)}")

            self.logger.info(
                f"Download phase complete: {downloaded_count}/{expected_files_count} required files downloaded"
                f" ({already_with_s3} already in S3 from prior run)"
            )

            # Step 3: Upload files with individual tracking
            upload_tracking = self._upload_files_with_individual_tracking(downloaded_files, config, billing_cycle)

            # Step 4: Determine final success based on download and upload results.
            # Files that were already in S3 (skipped by the scraper) are not failures.
            # Only required files contribute to download_failures; missing optional files never do.
            download_failures = max(0, expected_files_count - effective_count)
            upload_failures = upload_tracking["failed_uploads"]
            total_failures = download_failures + upload_failures

            # Build detailed result message
            if total_failures == 0:
                # Perfect success: all required files downloaded (or already in S3) and uploaded
                optional_note = f" (plus {len(optional_cycle_files)} optional)" if optional_cycle_files else ""
                message = (
                    f"SUCCESS: {expected_files_count}/{expected_files_count} required files"
                    f"{optional_note} downloaded and uploaded"
                )
                self.logger.info(message)
                self._cleanup_job_directory()
                return ScraperResult(True, message, self._create_file_mapping(upload_tracking["uploaded_files"]))
            else:
                # Partial or complete failure - keep folder for investigation
                error_parts = []

                if download_failures > 0:
                    error_parts.append(f"{download_failures} required file(s) failed to download")

                if upload_failures > 0:
                    error_parts.append(f"{upload_failures} file(s) failed to upload")
                    # Log details of failed uploads
                    for failed in upload_tracking["failed_files"]:
                        self.logger.error(f"Upload failure: {failed['file'].file_name} - {failed['reason']}")

                error_message = f"ERROR: {', '.join(error_parts)}. "
                error_message += f"Expected: {expected_files_count} required, "
                error_message += f"Downloaded: {downloaded_count}, "
                error_message += f"Uploaded: {upload_tracking['successful_uploads']}"

                self.logger.error(error_message)
                self.logger.warning(f"Folder job_{self.job_id} kept due to errors")

                # Return failure with partial results
                return ScraperResult(
                    False,
                    error_message,
                    self._create_file_mapping(upload_tracking["uploaded_files"]),
                    error=error_message,
                )

        except Exception as e:
            self.logger.error(f"Exception in execute(): {str(e)}")
            return ScraperResult(False, error=str(e))

    @abstractmethod
    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        raise NotImplementedError()

    @abstractmethod
    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        raise NotImplementedError()


class DailyUsageScraperStrategy(ScraperBaseStrategy):
    # Additional data for daily usage upload - override in subclasses to set actual values
    pool_size: int = 0
    pool_used: int = 0

    def execute(self, config: ScraperConfig, billing_cycle: BillingCycle, credentials: Credentials) -> ScraperResult:
        try:
            self._prepare_job_directory()
            # Expose credentials to _find_files_section so carrier scrapers can re-auth
            # mid-flow (e.g. Telus IQ shows its own login during the OAuth handshake).
            self.credentials = credentials

            files_section = self._find_files_section(config, billing_cycle)
            if not files_section:
                return ScraperResult(False, error="Could not find files section")

            downloaded_files = self._download_files(files_section, config, billing_cycle)
            if not downloaded_files:
                return ScraperResult(False, error="Could not download files")

            upload_result = self._upload_files_to_endpoint(downloaded_files, config, billing_cycle)
            if not upload_result:
                return ScraperResult(False, error="Error sending files to external endpoint")

            self._cleanup_job_directory()
            return ScraperResult(
                True, f"Processed {len(downloaded_files)} files", self._create_file_mapping(downloaded_files)
            )

        except Exception as e:
            return ScraperResult(False, error=str(e))

    def _upload_files_to_endpoint(
        self, files: List[FileDownloadInfo], config: ScraperConfig, billing_cycle: BillingCycle
    ) -> bool:
        """Upload daily usage file with additional pool data."""
        try:
            upload_service = FileUploadService()
            file_info = files[0]
            additional_data = {
                "pool_size": self.pool_size,
                "pool_used": self.pool_used,
            }

            return upload_service._upload_single_file(
                file_info=file_info,
                billing_cycle=billing_cycle,
                upload_type="daily_usage",
                additional_data=additional_data,
            )

        except Exception as e:
            self.logger.error(f"Error uploading files: {str(e)}")
            return False

    @abstractmethod
    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        raise NotImplementedError()

    @abstractmethod
    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        raise NotImplementedError()


class PDFInvoiceScraperStrategy(ScraperBaseStrategy):

    def execute(self, config: ScraperConfig, billing_cycle: BillingCycle, credentials: Credentials) -> ScraperResult:
        try:
            self.logger.info("=" * 70)
            self.logger.info("PDF INVOICE SCRAPER - STARTING EXECUTION")
            self.logger.info("=" * 70)
            self.logger.info(f"Account: {billing_cycle.account.number if billing_cycle.account else 'N/A'}")
            self.logger.info(f"Billing Cycle ID: {billing_cycle.id}")
            self.logger.info(f"Period: {billing_cycle.start_date} to {billing_cycle.end_date}")
            self.logger.info("-" * 70)

            self._prepare_job_directory()

            # Step 1: Find files section
            self.logger.info("[Step 1/3] Finding files section...")
            files_section = self._find_files_section(config, billing_cycle)
            if not files_section:
                error_msg = "Could not find files section for PDF invoice"
                self.logger.error(f"[Step 1/3] FAILED: {error_msg}")
                return ScraperResult(False, error=error_msg)
            self.logger.info("[Step 1/3] OK - Files section found")

            # Step 2: Download files
            self.logger.info("[Step 2/3] Downloading PDF files...")
            downloaded_files = self._download_files(files_section, config, billing_cycle)
            if not downloaded_files:
                error_msg = "Could not download PDF files"
                self.logger.error(f"[Step 2/3] FAILED: {error_msg}")
                return ScraperResult(False, error=error_msg)
            self.logger.info(f"[Step 2/3] OK - Downloaded {len(downloaded_files)} file(s)")

            # Log downloaded files details
            for i, f in enumerate(downloaded_files, 1):
                self.logger.info(f"  [{i}] {f.file_name}")
                self.logger.info(f"      Path: {f.file_path}")
                self.logger.info(f"      PDF File ID: {f.pdf_file.id if f.pdf_file else 'NOT MAPPED'}")

            # Step 3: Upload files
            self.logger.info("[Step 3/3] Uploading PDF files to backend API...")
            upload_result, upload_error = self._upload_files_to_endpoint_with_details(
                downloaded_files, config, billing_cycle
            )

            if not upload_result:
                error_msg = f"Error uploading PDF files: {upload_error}"
                self.logger.error(f"[Step 3/3] FAILED: {error_msg}")
                self.logger.warning(f"Job directory kept for investigation: {self.job_downloads_dir}")
                return ScraperResult(False, error=error_msg)

            self.logger.info("[Step 3/3] OK - All files uploaded successfully")
            self._cleanup_job_directory()

            self.logger.info("=" * 70)
            self.logger.info("PDF INVOICE SCRAPER - COMPLETED SUCCESSFULLY")
            self.logger.info("=" * 70)

            return ScraperResult(
                True, f"Processed {len(downloaded_files)} PDF files", self._create_file_mapping(downloaded_files)
            )

        except Exception as e:
            error_msg = f"Exception in PDF Invoice scraper: {str(e)}"
            self.logger.error(error_msg)
            self.logger.error(traceback.format_exc())
            return ScraperResult(False, error=error_msg)

    def _upload_files_to_endpoint_with_details(
        self, files: List[FileDownloadInfo], config: ScraperConfig, billing_cycle: BillingCycle
    ) -> tuple[bool, str]:
        """Upload PDF files with detailed error reporting.

        Returns:
            Tuple of (success: bool, error_message: str)
        """
        try:
            upload_service = FileUploadService()

            self.logger.info(f"[UPLOAD] Starting upload of {len(files)} PDF file(s)")
            self.logger.info(f"[UPLOAD] API Base URL: {upload_service.api_base_url}")
            self.logger.info(f"[UPLOAD] API Key configured: {'Yes' if upload_service.api_key else 'NO - MISSING!'}")

            if not upload_service.api_key:
                return False, "EIQ_BACKEND_API_KEY not configured"

            errors = []
            success_count = 0

            for i, file_info in enumerate(files, 1):
                self.logger.info(f"[UPLOAD] Processing file {i}/{len(files)}: {file_info.file_name}")

                # Verificar que el archivo existe
                if not file_info.file_path or not os.path.exists(file_info.file_path):
                    error = f"File not found on disk: {file_info.file_path}"
                    self.logger.error(f"[UPLOAD] {error}")
                    errors.append(error)
                    continue

                # Verificar que tiene pdf_file mapping
                if not file_info.pdf_file:
                    error = f"No pdf_file mapping for {file_info.file_name} - cannot determine upload endpoint"
                    self.logger.error(f"[UPLOAD] {error}")
                    errors.append(error)
                    continue

                # Construir URL
                url = f"{upload_service.api_base_url}/api/v1/billing-cycles/{billing_cycle.id}/upload-pdf/"
                self.logger.info(f"[UPLOAD] URL: {url}")

                # Intentar upload
                try:
                    result = upload_service._upload_single_file(
                        file_info=file_info,
                        billing_cycle=billing_cycle,
                        upload_type="pdf_invoice",
                    )

                    if result:
                        self.logger.info(f"[UPLOAD] SUCCESS: {file_info.file_name}")
                        success_count += 1
                    else:
                        error = f"Upload failed for {file_info.file_name} - service returned False"
                        self.logger.error(f"[UPLOAD] {error}")
                        errors.append(error)

                except Exception as upload_exc:
                    error = f"Exception uploading {file_info.file_name}: {str(upload_exc)}"
                    self.logger.error(f"[UPLOAD] {error}")
                    errors.append(error)

            # Resumen
            self.logger.info(f"[UPLOAD] SUMMARY: {success_count}/{len(files)} files uploaded successfully")

            if errors:
                error_summary = f"{len(errors)} upload error(s): " + "; ".join(errors[:3])
                if len(errors) > 3:
                    error_summary += f" ... and {len(errors) - 3} more"
                return False, error_summary

            return True, ""

        except Exception as e:
            error_msg = f"Exception in upload process: {str(e)}"
            self.logger.error(error_msg)
            self.logger.error(traceback.format_exc())
            return False, error_msg

    @abstractmethod
    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        raise NotImplementedError()

    @abstractmethod
    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        raise NotImplementedError()
