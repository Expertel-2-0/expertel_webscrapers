from shared.infrastructure.django.repositories import DjangoFullRepository
from web_scrapers.domain.entities.models import (
    Account as AccountEntity,
    BillingCycle as BillingCycleEntity,
    BillingCycleDailyUsageFile as BillingCycleDailyUsageFileEntity,
    BillingCycleFile as BillingCycleFileEntity,
    BillingCyclePDFFile as BillingCyclePDFFileEntity,
    Carrier as CarrierEntity,
    CarrierPortalCredential as CarrierPortalCredentialEntity,
    CarrierReport as CarrierReportEntity,
    Client as ClientEntity,
    ScraperConfig as ScraperConfigEntity,
    ScraperJob as ScraperJobEntity,
    Workspace as WorkspaceEntity,
)
from web_scrapers.infrastructure.django.models import (
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
    Workspace,
)


class ClientRepository(DjangoFullRepository[ClientEntity, Client]):
    __model__: Client = Client

    def to_entity(self, model: Client) -> ClientEntity:
        return ClientEntity(
            id=model.pk,
            contact_name=model.contact_name,
            contact_email=model.contact_email,
            name=model.name,
            address=model.address,
            city=model.city,
            zip_code=model.zip_code,
            phone_number=model.phone_number if model.phone_number else None,
            related_collection=model.related_collection if model.related_collection else None,
            is_trial=model.is_trial,
            trial_ends=model.trial_ends,
            active=model.active,
            managed_by_expertel=model.managed_by_expertel,
        )

    def to_orm_model(self, entity: ClientEntity) -> Client:
        return Client(
            id=entity.id,
            name=entity.name,
            contact_name=entity.contact_name,
            contact_email=entity.contact_email,
            address=entity.address,
            city=entity.city,
            zip_code=entity.zip_code,
            phone_number=entity.phone_number,
            related_collection=entity.related_collection,
            is_testing=entity.is_testing,
            trial_ends=entity.trial_ends,
            active=entity.active,
            managed_by_expertel=entity.managed_by_expertel,
        )


class WorkspaceRepository(DjangoFullRepository[WorkspaceEntity, Workspace]):
    __model__: Workspace = Workspace

    def to_entity(self, model: Workspace) -> WorkspaceEntity:
        return WorkspaceEntity(
            id=model.pk,
            name=model.name,
            client_id=model.client.id,
        )

    def to_orm_model(self, entity: WorkspaceEntity) -> Workspace:
        return Workspace(
            id=entity.id,
            name=entity.name,
            client_id=entity.client_id,
        )


class CarrierRepository(DjangoFullRepository[CarrierEntity, Carrier]):
    __model__: Carrier = Carrier

    def to_entity(self, model: Carrier) -> CarrierEntity:
        return CarrierEntity(
            id=model.pk,
            name=model.name,
            logo=model.logo,
            metadata=model.metadata,
        )

    def to_orm_model(self, entity: CarrierEntity) -> Carrier:
        return Carrier(
            id=entity.id,
            name=entity.name,
            logo=entity.logo,
            metadata=entity.metadata,
        )


class AccountRepository(DjangoFullRepository[AccountEntity, Account]):
    __model__: Account = Account

    def to_entity(self, model: Account) -> AccountEntity:
        return AccountEntity(
            id=model.pk,
            number=model.number,
            nickname=model.nickname,
            workspace_id=model.workspace.id,
            carrier_id=model.carrier.id,
            account_type=model.account_type,
            billing_day=model.billing_day if model.billing_day is not None else 15,
            description=model.description if model.description else None,
        )

    def to_orm_model(self, entity: AccountEntity) -> Account:
        account: Account = self.__model__.objects.get(pk=entity.id)
        updated_fields = []
        for field in [
            "number",
            "nickname",
            "workspace_id",
            "carrier_id",
            "account_type",
            "billing_day",
            "description",
        ]:
            value = getattr(entity, field)
            if getattr(account, field) != value:
                setattr(account, field, value)
                updated_fields.append(field)
        return account


class BillingCycleRepository(DjangoFullRepository[BillingCycleEntity, BillingCycle]):
    __model__: BillingCycle = BillingCycle

    def to_entity(self, model: BillingCycle) -> BillingCycleEntity:
        return BillingCycleEntity(
            id=model.pk,
            start_date=model.start_date,
            end_date=model.end_date,
            account_id=model.account.id,
            status=model.status,
        )

    def to_orm_model(self, entity: BillingCycleEntity) -> BillingCycle:
        return BillingCycle(
            id=entity.id,
            start_date=entity.start_date,
            end_date=entity.end_date,
            account_id=entity.account_id,
            status=entity.status,
        )


class CarrierReportRepository(DjangoFullRepository[CarrierReportEntity, CarrierReport]):
    __model__: CarrierReport = CarrierReport

    def to_entity(self, model: CarrierReport) -> CarrierReportEntity:
        return CarrierReportEntity(
            id=model.pk,
            name=model.name,
            carrier_id=model.carrier.id,
            slug=model.slug,
            details=model.details,
            required=model.required,
        )

    def to_orm_model(self, entity: CarrierReportEntity) -> CarrierReport:
        return CarrierReport(
            id=entity.id,
            name=entity.name,
            carrier_id=entity.carrier_id,
            slug=entity.slug,
            details=entity.details,
            required=entity.required,
        )


class BillingCycleFileRepository(DjangoFullRepository[BillingCycleFileEntity, BillingCycleFile]):
    __model__: BillingCycleFile = BillingCycleFile

    def to_entity(self, model: BillingCycleFile) -> BillingCycleFileEntity:
        return BillingCycleFileEntity(
            id=model.pk,
            billing_cycle_id=model.billing_cycle.id,
            carrier_report_id=model.carrier_report.id,
            status=model.status,
            s3_key=model.s3_key,
            status_comment=model.status_comment,
        )

    def to_orm_model(self, entity: BillingCycleFileEntity) -> BillingCycleFile:
        return BillingCycleFile(
            id=entity.id,
            billing_cycle_id=entity.billing_cycle_id,
            carrier_report_id=entity.carrier_report_id,
            status=entity.status,
            status_comment=entity.status_comment,
            s3_key=entity.s3_key,
        )


class CarrierPortalCredentialRepository(DjangoFullRepository[CarrierPortalCredentialEntity, CarrierPortalCredential]):
    __model__: CarrierPortalCredential = CarrierPortalCredential

    def to_entity(self, model: CarrierPortalCredential) -> CarrierPortalCredentialEntity:
        return CarrierPortalCredentialEntity(
            id=model.pk,
            username=model.username,
            password=model.password,
            client_id=model.client.id,
            carrier_id=model.carrier.id,
            nickname=model.nickname,
        )

    def to_orm_model(self, entity: CarrierPortalCredentialEntity) -> CarrierPortalCredential:
        return CarrierPortalCredential(
            id=entity.id,
            username=entity.username,
            password=entity.password,
            client_id=entity.client_id,
            carrier_id=entity.carrier_id,
            nickname=entity.nickname,
        )


class BillingCycleDailyUsageFileRepository(
    DjangoFullRepository[BillingCycleDailyUsageFileEntity, BillingCycleDailyUsageFile]
):
    __model__: BillingCycleDailyUsageFile = BillingCycleDailyUsageFile

    def to_entity(self, model: BillingCycleDailyUsageFile) -> BillingCycleDailyUsageFileEntity:
        return BillingCycleDailyUsageFileEntity(
            id=model.pk,
            billing_cycle_id=model.billing_cycle.id,
            status=model.status,
            s3_key=model.s3_key,
        )

    def to_orm_model(self, entity: BillingCycleDailyUsageFileEntity) -> BillingCycleDailyUsageFile:
        return BillingCycleDailyUsageFile(
            id=entity.id,
            billing_cycle_id=entity.billing_cycle_id,
            status=entity.status,
            s3_key=entity.s3_key,
        )


class ScraperConfigRepository(DjangoFullRepository[ScraperConfigEntity, ScraperConfig]):
    __model__: ScraperConfig = ScraperConfig

    def to_entity(self, model: ScraperConfig) -> ScraperConfigEntity:
        return ScraperConfigEntity(
            id=model.pk,
            account_id=model.account.id,
            credential_id=model.credential.id,
            carrier_id=model.carrier.id,
            parameters=model.parameters,
            days_offset=model.days_offset,
        )

    def to_orm_model(self, entity: ScraperConfigEntity) -> ScraperConfig:
        return ScraperConfig(
            id=entity.id,
            account_id=entity.account_id,
            credential_id=entity.credential_id,
            carrier_id=entity.carrier_id,
            parameters=entity.parameters,
            days_offset=entity.days_offset,
        )


class ScraperJobRepository(DjangoFullRepository[ScraperJobEntity, ScraperJob]):
    __model__: ScraperJob = ScraperJob

    def to_entity(self, model: ScraperJob) -> ScraperJobEntity:
        return ScraperJobEntity(
            id=model.pk,
            billing_cycle_id=model.billing_cycle.id,
            scraper_config_id=model.scraper_config.id,
            status=model.status,
            type=model.type,
            log=model.log,
            completed_at=model.completed_at,
            available_at=model.available_at,
            retry_count=model.retry_count,
            max_retries=model.max_retries,
        )

    def to_orm_model(self, entity: ScraperJobEntity) -> ScraperJob:
        return ScraperJob(
            id=entity.id,
            billing_cycle_id=entity.billing_cycle_id,
            scraper_config_id=entity.scraper_config_id,
            status=entity.status,
            type=entity.type,
            log=entity.log,
            completed_at=entity.completed_at,
            available_at=entity.available_at,
            retry_count=entity.retry_count,
            max_retries=entity.max_retries,
        )


class BillingCyclePDFFileRepository(DjangoFullRepository[BillingCyclePDFFileEntity, BillingCyclePDFFile]):
    __model__: BillingCyclePDFFile = BillingCyclePDFFile

    def to_entity(self, model: BillingCyclePDFFile) -> BillingCyclePDFFileEntity:
        return BillingCyclePDFFileEntity(
            id=model.pk,
            billing_cycle_id=model.billing_cycle.id,
            status=model.status,
            status_comment=model.status_comment,
            s3_key=model.s3_key,
            pdf_type=model.pdf_type,
        )

    def to_orm_model(self, entity: BillingCyclePDFFileEntity) -> BillingCyclePDFFile:
        return BillingCyclePDFFile(
            id=entity.id,
            billing_cycle_id=entity.billing_cycle_id,
            status=entity.status,
            status_comment=entity.status_comment,
            s3_key=entity.s3_key,
            pdf_type=entity.pdf_type,
        )
