from enum import StrEnum


class DataMode(StrEnum):
    POL_Q = "POL_Q"
    POL_U = "POL_U"
    POL_V = "POL_V"
    NONPOL = "NONPOL"

    @property
    def is_polarimetric(self) -> bool:
        return self is not DataMode.NONPOL


class InstrumentState(StrEnum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    STANDBY = "STANDBY"
    PREPARING = "PREPARING"
    READY = "READY"
    EXPOSING = "EXPOSING"
    READING = "READING"
    CALIBRATING = "CALIBRATING"
    MAINTENANCE = "MAINTENANCE"
    SAFE_FAULT = "SAFE_FAULT"


class SequenceStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExposureStatus(StrEnum):
    PENDING = "PENDING"
    EXPOSING = "EXPOSING"
    READING = "READING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    REPLACED = "REPLACED"


class CommandStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"


class ProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CALIBRATION = "WAITING_CALIBRATION"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ImportStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class PublicationStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class ProductLevel(StrEnum):
    QUICKLOOK = "QUICKLOOK"
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ConfigurationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class QCFlag(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    SIMULATION_ONLY = "SIMULATION_ONLY"


class AlarmSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    SERIOUS = "SERIOUS"
    EMERGENCY = "EMERGENCY"


class Role(StrEnum):
    OBSERVER = "observer"
    INSTRUMENT_ENGINEER = "instrument_engineer"
    DATA_REDUCER = "data_reducer"
    ADMINISTRATOR = "administrator"


class EventType(StrEnum):
    RAW_FILE_COMMITTED = "raw_file.committed.v1"
    SEQUENCE_STATE_CHANGED = "sequence.state.changed.v1"
    DEVICE_STATE_CHANGED = "device.state.changed.v1"
    PROCESSING_RUN_STATE_CHANGED = "processing_run.state.changed.v1"
    ALARM_RAISED = "alarm.raised.v1"
    IMPORT_INSPECTION_COMPLETED = "import.inspection.completed.v1"
    IMPORT_COMPLETED = "import.completed.v1"
    CALIBRATION_RUN_STATE_CHANGED = "calibration_run.state.changed.v1"
    CALIBRATION_SET_STATE_CHANGED = "calibration_set.state.changed.v1"
    PRODUCT_PUBLICATION_CHANGED = "product.publication.changed.v1"


class DQBit:
    SATURATED = 1 << 0
    COSMIC_RAY = 1 << 1
    BAD_PIXEL = 1 << 2
    EXTRACTION_FAILED = 1 << 3
    RESAMPLE_EDGE = 1 << 4
    MISSING_CALIBRATION = 1 << 5
    REPLACED_EXPOSURE = 1 << 6
    NULL1_EXCESS = 1 << 7
    NULL2_EXCESS = 1 << 8
    MANUAL_REJECT = 1 << 9
    SKY_INVALID = 1 << 10
    ORDER_GAP = 1 << 11
    NORMALIZATION_FAILED = 1 << 12
    WAVELENGTH_FAILED = 1 << 13
