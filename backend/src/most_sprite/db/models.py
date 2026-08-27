from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from most_sprite.domain.enums import (
    CommandStatus,
    ConfigurationStatus,
    ExposureStatus,
    InstrumentState,
    ProcessingStatus,
    QCFlag,
    SequenceStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConfigSnapshot(Base, TimestampMixin):
    __tablename__ = "config_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default=ConfigurationStatus.UNVERIFIED)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class Sequence(Base, TimestampMixin):
    __tablename__ = "sequences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    target_name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16))
    exposure_time: Mapped[float] = mapped_column(Float)
    repeats: Mapped[int] = mapped_column(Integer, default=1)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    expected_exposures: Mapped[int] = mapped_column(Integer)
    completed_exposures: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=SequenceStatus.DRAFT)
    config_snapshot_id: Mapped[str] = mapped_column(ForeignKey("config_snapshots.id"))
    created_by: Mapped[str] = mapped_column(String(128))
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModulationGroup(Base, TimestampMixin):
    __tablename__ = "modulation_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"), index=True)
    group_index: Mapped[int] = mapped_column(Integer, default=1)
    stokes: Mapped[str] = mapped_column(String(1))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")


class Command(Base, TimestampMixin):
    __tablename__ = "commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    sequence_id: Mapped[str | None] = mapped_column(ForeignKey("sequences.id"), nullable=True)
    device_id: Mapped[str] = mapped_column(String(64))
    command_type: Mapped[str] = mapped_column(String(64))
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=CommandStatus.ACCEPTED)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Exposure(Base, TimestampMixin):
    __tablename__ = "exposures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("modulation_groups.id"), nullable=True)
    command_id: Mapped[str | None] = mapped_column(ForeignKey("commands.id"), nullable=True)
    sub_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=ExposureStatus.PENDING)
    fr1_commanded: Mapped[float | None] = mapped_column(Float, nullable=True)
    fr1_measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    fr3_commanded: Mapped[float | None] = mapped_column(Float, nullable=True)
    fr3_measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(ForeignKey("exposures.id"), nullable=True)


class RawFile(Base, TimestampMixin):
    __tablename__ = "raw_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    exposure_id: Mapped[str] = mapped_column(ForeignKey("exposures.id"), unique=True)
    uri: Mapped[str] = mapped_column(Text, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    fits_checksum: Mapped[str] = mapped_column(String(32))
    fits_datasum: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="COMMITTED")
    instrument: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detector_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("imported_artifacts.id"), nullable=True
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), default=uuid_str, unique=True)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sequence_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    exposure_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    config_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsumedEvent(Base):
    __tablename__ = "consumed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingRun(Base, TimestampMixin):
    __tablename__ = "processing_runs"
    __table_args__ = (
        UniqueConstraint(
            "input_hash",
            "calibration_hash",
            "parameter_hash",
            "code_hash",
            name="uq_processing_run_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ProcessingStatus.QUEUED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    input_hash: Mapped[str] = mapped_column(String(64))
    calibration_hash: Mapped[str] = mapped_column(String(64))
    parameter_hash: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    calibration_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("calibration_sets.id"), nullable=True
    )
    parameter_version: Mapped[str] = mapped_column(String(64), default="simulation-v1")
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    claim_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("processing_run_id", "task_name", name="uq_task_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id"))
    task_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=ProcessingStatus.QUEUED)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    processing_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("processing_runs.id"), nullable=True
    )
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"), index=True)
    exposure_id: Mapped[str | None] = mapped_column(ForeignKey("exposures.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    uri: Mapped[str] = mapped_column(Text, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    product_hash: Mapped[str] = mapped_column(String(64), unique=True)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    qc_flag: Mapped[str] = mapped_column(String(32), default=QCFlag.SIMULATION_ONLY)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    instrument: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detector_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    calibration_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("calibration_sets.id"), nullable=True
    )
    publication_status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    published_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def download_url(self) -> str:
        return f"/api/v1/products/{self.id}/download"


class ProductInput(Base):
    __tablename__ = "product_inputs"
    __table_args__ = (UniqueConstraint("product_id", "input_id", name="uq_product_input"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    input_id: Mapped[str] = mapped_column(String(36))
    input_kind: Mapped[str] = mapped_column(String(32))
    input_checksum: Mapped[str] = mapped_column(String(64))


class QCResult(Base):
    __tablename__ = "qc_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    reason_code: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Calibration(Base, TimestampMixin):
    __tablename__ = "calibrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    calibration_type: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    uri: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=ConfigurationStatus.UNVERIFIED)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("calibrations.id"), nullable=True)
    calibration_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("calibration_sets.id"), nullable=True, index=True
    )


class ImportInspection(Base, TimestampMixin):
    __tablename__ = "import_inspections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    root_id: Mapped[str] = mapped_column(String(64))
    relative_path: Mapped[str] = mapped_column(Text)
    instrument: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    inventory_json: Mapped[list] = mapped_column(JSON, default=list)
    groups_json: Mapped[list] = mapped_column(JSON, default=list)
    calibration_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("import_inspections.id"), unique=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    sequence_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))


class ImportedArtifact(Base, TimestampMixin):
    __tablename__ = "imported_artifacts"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "relative_path", name="uq_import_artifact_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    relative_path: Mapped[str] = mapped_column(Text)
    managed_uri: Mapped[str] = mapped_column(Text, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    artifact_role: Mapped[str] = mapped_column(String(64), index=True)
    instrument: Mapped[str] = mapped_column(String(32))
    detector: Mapped[str] = mapped_column(String(64))
    header_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sequence_id: Mapped[str | None] = mapped_column(ForeignKey("sequences.id"), nullable=True)
    exposure_id: Mapped[str | None] = mapped_column(ForeignKey("exposures.id"), nullable=True)


class CalibrationRun(Base, TimestampMixin):
    __tablename__ = "calibration_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), default=ProcessingStatus.QUEUED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    parameter_version: Mapped[str] = mapped_column(String(64), default="espadons-olapa-v1")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))


class CalibrationSet(Base, TimestampMixin):
    __tablename__ = "calibration_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    calibration_run_id: Mapped[str] = mapped_column(
        ForeignKey("calibration_runs.id"), unique=True
    )
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    instrument: Mapped[str] = mapped_column(String(32), index=True)
    detector: Mapped[str] = mapped_column(String(64), index=True)
    observing_night: Mapped[str] = mapped_column(String(16), index=True)
    readout_mode: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default=ConfigurationStatus.UNVERIFIED)
    calibration_hash: Mapped[str] = mapped_column(String(64), unique=True)
    artifact_uri: Mapped[str] = mapped_column(Text)
    qc_flag: Mapped[str] = mapped_column(String(32), default=QCFlag.WARNING)
    qc_json: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Alarm(Base):
    __tablename__ = "alarms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    sequence_id: Mapped[str | None] = mapped_column(ForeignKey("sequences.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    protective_action: Mapped[str] = mapped_column(Text)
    recovery_condition: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(96))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstrumentStateRecord(Base):
    __tablename__ = "instrument_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[str] = mapped_column(String(32), default=InstrumentState.OFFLINE)
    target_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    devices_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ControlLease(Base):
    __tablename__ = "control_lease"

    name: Mapped[str] = mapped_column(String(64), primary_key=True, default="primary")
    owner_id: Mapped[str] = mapped_column(String(64))
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
