from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from most_sprite.domain.enums import (
    CommandStatus,
    ConfigurationStatus,
    DataMode,
    ExposureStatus,
    ImportStatus,
    InstrumentState,
    ProcessingStatus,
    ProductLevel,
    PublicationStatus,
    QCFlag,
    Role,
    SequenceStatus,
)


class ApiModel(BaseModel):
    # Keep enum instances inside the domain so behavior such as
    # DataMode.is_polarimetric remains available. JSON serialization still emits
    # their stable string values because the enums inherit from StrEnum.
    model_config = ConfigDict(from_attributes=True)


class SequenceRequest(ApiModel):
    target_name: str = Field(min_length=1, max_length=128)
    mode: DataMode
    exposure_time: float = Field(gt=0, le=7200)
    repeats: int = Field(default=1, ge=1, le=100)

    @field_validator("target_name")
    @classmethod
    def strip_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_name cannot be blank")
        return value


class ValidationIssue(ApiModel):
    code: str
    message: str
    blocking: bool = True


class SequenceValidation(ApiModel):
    valid: bool
    estimated_exposures: int
    estimated_duration: float
    config_snapshot_id: UUID
    issues: list[ValidationIssue] = Field(default_factory=list)


class CommandAccepted(ApiModel):
    command_id: UUID
    resource_id: UUID | None = None
    status: CommandStatus = CommandStatus.ACCEPTED


class CommandRead(ApiModel):
    id: UUID
    sequence_id: UUID | None
    device_id: str
    command_type: str
    status: CommandStatus
    issued_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    fencing_token: int


class SequenceRead(ApiModel):
    id: UUID
    target_name: str
    mode: DataMode
    exposure_time: float
    repeats: int
    attempt: int
    expected_exposures: int
    completed_exposures: int
    status: SequenceStatus
    config_snapshot_id: UUID
    created_by: str
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


class ExposureRead(ApiModel):
    id: UUID
    sequence_id: UUID
    group_id: UUID | None
    sub_index: int
    status: ExposureStatus
    fr1_commanded: float | None
    fr1_measured: float | None
    fr3_commanded: float | None
    fr3_measured: float | None
    raw_file_id: UUID | None
    started_at: datetime | None
    committed_at: datetime | None


class InstrumentSnapshot(ApiModel):
    state: InstrumentState
    target_state: InstrumentState | None
    observed_at: datetime
    fresh: bool
    fencing_token: int
    devices: dict[str, Any] = Field(default_factory=dict)


class ProcessingRunRead(ApiModel):
    id: UUID
    sequence_id: UUID
    status: ProcessingStatus
    progress: float
    input_hash: str
    calibration_hash: str
    parameter_hash: str
    code_hash: str
    calibration_set_id: UUID | None = None
    parameter_version: str = "simulation-v1"
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ProcessingRunRequest(ApiModel):
    sequence_id: UUID
    calibration_set_id: UUID | None = None
    parameter_version: str = Field(default="simulation-v1", min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProductRead(ApiModel):
    id: UUID
    processing_run_id: UUID | None
    sequence_id: UUID
    exposure_id: UUID | None
    level: ProductLevel
    mode: DataMode
    size: int
    sha256: str
    schema_version: str
    qc_flag: QCFlag
    instrument: str | None = None
    detector_profile: str | None = None
    calibration_set_id: UUID | None = None
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    download_url: str | None = None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime


class ProcessingStageRead(ApiModel):
    key: Literal["l0", "quicklook", "l1", "l2", "l3"]
    order: int
    level: ProductLevel
    status: Literal[
        "AVAILABLE",
        "RUNNING",
        "PENDING",
        "PARTIAL",
        "FAILED",
        "BLOCKED",
        "NOT_AVAILABLE",
    ]
    preview_kind: Literal["image", "spectrum"]
    optional: bool = False
    expected_output_count: int
    products: list[ProductRead] = Field(default_factory=list)


class ProductPublicationRequest(ApiModel):
    reason: str | None = Field(default=None, min_length=8, max_length=2048)


class CalibrationCreate(ApiModel):
    calibration_type: str
    mode: DataMode | None = None
    uri: str
    checksum: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("parameters", "parameters_json"),
    )


class CalibrationRead(CalibrationCreate):
    id: UUID
    status: ConfigurationStatus
    created_at: datetime


class ImportInspectionRequest(ApiModel):
    root_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    relative_path: str = Field(default=".", min_length=1, max_length=2048)
    instrument: Literal["ESPADONS"] = "ESPADONS"


class ImportInspectionRead(ApiModel):
    id: UUID
    root_id: str
    relative_path: str
    instrument: str
    status: ImportStatus
    manifest_sha256: str | None
    inventory: list[dict[str, Any]] = Field(validation_alias="inventory_json")
    groups: list[dict[str, Any]] = Field(validation_alias="groups_json")
    calibration_summary: dict[str, Any] = Field(validation_alias="calibration_summary_json")
    warnings: list[dict[str, Any]] = Field(validation_alias="warnings_json")
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ImportCommitRequest(ApiModel):
    inspection_id: UUID
    manifest_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class ImportBatchRead(ApiModel):
    id: UUID
    inspection_id: UUID
    manifest_sha256: str
    status: ImportStatus
    sequence_ids: list[UUID] = Field(validation_alias="sequence_ids_json")
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CalibrationRunRequest(ApiModel):
    import_batch_id: UUID
    parameter_version: str = Field(default="espadons-olapa-v1", min_length=1, max_length=64)


class CalibrationRunRead(ApiModel):
    id: UUID
    import_batch_id: UUID
    status: ProcessingStatus
    progress: float
    parameter_version: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CalibrationSetRead(ApiModel):
    id: UUID
    calibration_run_id: UUID
    import_batch_id: UUID
    instrument: str
    detector: str
    observing_night: str
    readout_mode: str
    status: ConfigurationStatus
    calibration_hash: str
    qc_flag: QCFlag
    qc: dict[str, Any] = Field(validation_alias="qc_json")
    warnings: list[dict[str, Any]] = Field(validation_alias="warnings_json")
    approved_by: str | None
    approved_at: datetime | None
    approval_reason: str | None
    created_at: datetime
    updated_at: datetime


class CalibrationSetApproval(ApiModel):
    reason: str = Field(min_length=8, max_length=2048)
    accept_warnings: bool = False


class ErrorEnvelope(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    retryable: bool = False


class EventEnvelope(ApiModel):
    cursor: int | None = None
    event_id: UUID
    event_type: str
    schema_version: int = 1
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    sequence_id: UUID | None = None
    group_id: UUID | None = None
    exposure_id: UUID | None = None
    config_snapshot_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CurrentUser(ApiModel):
    subject: str
    display_name: str
    role: Role
    auth_mode: Literal["dev", "oidc"]


class PreviewSeries(ApiModel):
    product_id: UUID
    level: ProductLevel
    mode: DataMode
    columns: dict[str, list[float | None]]
    metadata: dict[str, Any]
