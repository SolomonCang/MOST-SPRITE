from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceCommand(_message.Message):
    __slots__ = (
        "command_id",
        "idempotency_key",
        "sequence_id",
        "device_id",
        "command_type",
        "parameters_json",
        "issued_at",
        "deadline",
        "expected_pre_state",
        "config_snapshot_id",
        "fencing_token",
    )
    COMMAND_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    COMMAND_TYPE_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    ISSUED_AT_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_PRE_STATE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    FENCING_TOKEN_FIELD_NUMBER: _ClassVar[int]
    command_id: str
    idempotency_key: str
    sequence_id: str
    device_id: str
    command_type: str
    parameters_json: str
    issued_at: str
    deadline: str
    expected_pre_state: str
    config_snapshot_id: str
    fencing_token: int
    def __init__(
        self,
        command_id: _Optional[str] = ...,
        idempotency_key: _Optional[str] = ...,
        sequence_id: _Optional[str] = ...,
        device_id: _Optional[str] = ...,
        command_type: _Optional[str] = ...,
        parameters_json: _Optional[str] = ...,
        issued_at: _Optional[str] = ...,
        deadline: _Optional[str] = ...,
        expected_pre_state: _Optional[str] = ...,
        config_snapshot_id: _Optional[str] = ...,
        fencing_token: _Optional[int] = ...,
    ) -> None: ...

class DeviceFeedback(_message.Message):
    __slots__ = (
        "command_id",
        "status",
        "completed_at",
        "result_json",
        "error_code",
        "error_message",
    )
    COMMAND_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    command_id: str
    status: str
    completed_at: str
    result_json: str
    error_code: str
    error_message: str
    def __init__(
        self,
        command_id: _Optional[str] = ...,
        status: _Optional[str] = ...,
        completed_at: _Optional[str] = ...,
        result_json: _Optional[str] = ...,
        error_code: _Optional[str] = ...,
        error_message: _Optional[str] = ...,
    ) -> None: ...

class StateRequest(_message.Message):
    __slots__ = ("device_id",)
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    def __init__(self, device_id: _Optional[str] = ...) -> None: ...

class DeviceState(_message.Message):
    __slots__ = ("device_id", "state_json", "observed_at", "fencing_token")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_JSON_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_AT_FIELD_NUMBER: _ClassVar[int]
    FENCING_TOKEN_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    state_json: str
    observed_at: str
    fencing_token: int
    def __init__(
        self,
        device_id: _Optional[str] = ...,
        state_json: _Optional[str] = ...,
        observed_at: _Optional[str] = ...,
        fencing_token: _Optional[int] = ...,
    ) -> None: ...

class FaultRequest(_message.Message):
    __slots__ = ("fault_type", "active", "parameters_json")
    FAULT_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    fault_type: str
    active: bool
    parameters_json: str
    def __init__(
        self,
        fault_type: _Optional[str] = ...,
        active: _Optional[bool] = ...,
        parameters_json: _Optional[str] = ...,
    ) -> None: ...
