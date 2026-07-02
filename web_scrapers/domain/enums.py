from enum import Enum


class Navigators(str, Enum):
    CHROME = "chrome"
    FIREFOX = "firefox"
    EDGE = "edge"
    SAFARI = "safari"


class CarrierPortalUrls(str, Enum):
    ATT = "https://www.wireless.att.com/premiercare/"
    BELL = "https://business.bell.ca/corporateselfserve/Login"
    TELUS = "https://www.telus.com/en"
    ROGERS = "https://bss.rogers.com/bizonline/homePage.do"
    TMOBILE = "https://tfb.t-mobile.com"
    VERIZON = "https://mblogin.verizonwireless.com/account/business/ilogin"


class FileStatus(str, Enum):
    TO_BE_FETCHED = "to_be_fetched"
    READY = "ready"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class AccountType(str, Enum):
    CORPORATE = "corporate"
    INDIVIDUAL = "individual"


class BillingCycleStatus(str, Enum):
    OPEN = "open"
    READY_TO_PROCESS = "ready_to_process"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class PhoneNumberStatus(str, Enum):
    ACTIVE = "active"
    UNUSED = "unused"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ScraperJobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ScraperType(str, Enum):
    DAILY_USAGE = "daily_usage"
    MONTHLY_REPORTS = "monthly_reports"
    PDF_INVOICE = "pdf_invoice"


class BellFileSlug(str, Enum):
    COST_OVERVIEW = "cost_overview"
    ENHANCED_USER_PROFILE = "enhanced_user_profile"
    USAGE_OVERVIEW = "usage_overview"
    INVOICE_CHARGE_REPORT = "invoice_charge_report"


class TelusFileSlug(str, Enum):
    INDIVIDUAL_DETAIL = "individual_detail"
    MOBILITY_DEVICE = "mobility_device"
    GROUP_SUMMARY = "group_summary"
    AIRTIME_DETAIL = "airtime_detail"


class VerizonFileSlug(str, Enum):
    ACCOUNT_AND_WIRELESS = "account_wireless"
    WIRELESS_CHARGES_DETAIL = "wireless_charges_detail"
    DEVICE_REPORT = "device_report"
    SUSPENDED_WIRELESS_NUMBERS = "suspended_wireless_numbers"
    ACTIVATION_AND_DEACTIVATION = "activation_and_deactivation"
    WIRELESS_USAGE_DETAIL = "wireless_usage_detail"


class ATTFileSlug(str, Enum):
    WIRELESS_CHARGES = "wireless_charges"
    USAGE_DETAILS = "usage_details"
    MONTHLY_CHARGES = "monthly_charges"
    DEVICE_INSTALLMENT = "device_installment"
    UPGRADE_AND_INVENTORY = "upgrade_and_inventory"
    ALL_BILLING_CYCLE_CHARGES = "all_billing_cycle_charges"


class TmobileFileSlug(str, Enum):
    CHARGES_AND_USAGE = "charges_and_usage"
    USAGE_DETAIL = "usage_detail"
    INVENTORY_REPORT = "inventory_report"
    EQUIPMENT_INSTALLMENT = "equipment_installment"
    STATEMENT_DETAIL = "statement_detail"


class RogersFileSlug(str, Enum):
    CURRENT_CHARGES_SUBSCRIBER = "ccc_chg"
    MONTHLY_CHARGES_BREAKDOWN = "ccd_monthly"
    MONTHLY_USAGE_BREAKDOWN = "data"
    BALANCE_REMAINING = "bcr"
    CREDITS_SUBSCRIBER = "ccc_credits"