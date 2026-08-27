export type Role =
  | "observer"
  | "instrument_engineer"
  | "data_reducer"
  | "administrator";

export type DataMode = "POL_Q" | "POL_U" | "POL_V" | "NONPOL";
export type SequenceStatus =
  | "DRAFT"
  | "VALIDATED"
  | "QUEUED"
  | "RUNNING"
  | "PAUSING"
  | "PAUSED"
  | "ABORTING"
  | "ABORTED"
  | "SUCCEEDED"
  | "FAILED";
export type ProductLevel = "QUICKLOOK" | "L0" | "L1" | "L2" | "L3";

export interface CurrentUser {
  subject: string;
  display_name: string;
  role: Role;
  auth_mode: "dev" | "oidc";
}

export interface ValidationIssue {
  code: string;
  message: string;
  blocking: boolean;
}

export interface SequenceValidation {
  valid: boolean;
  estimated_exposures: number;
  estimated_duration: number;
  config_snapshot_id: string;
  issues: ValidationIssue[];
}

export interface SequencePayload {
  target_name: string;
  mode: DataMode;
  exposure_time: number;
  repeats: number;
}

export interface Sequence extends SequencePayload {
  id: string;
  expected_exposures: number;
  completed_exposures: number;
  attempt: number;
  status: SequenceStatus;
  config_snapshot_id: string;
  created_by: string;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Exposure {
  id: string;
  sequence_id: string;
  group_id: string | null;
  sub_index: number;
  status: string;
  fr1_commanded: number | null;
  fr1_measured: number | null;
  fr3_commanded: number | null;
  fr3_measured: number | null;
  raw_file_id: string | null;
  started_at: string | null;
  committed_at: string | null;
}

export interface AcceptedCommand {
  command_id: string;
  resource_id: string | null;
  status: string;
}

export interface InstrumentSnapshot {
  state: string;
  target_state: string | null;
  observed_at: string;
  fresh: boolean;
  fencing_token: number;
  devices: Record<string, unknown>;
}

export interface Product {
  id: string;
  processing_run_id: string | null;
  sequence_id: string;
  exposure_id: string | null;
  level: ProductLevel;
  mode: DataMode;
  uri: string;
  size: number;
  sha256: string;
  schema_version: string;
  qc_flag: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ProcessingRun {
  id: string;
  sequence_id: string;
  status: string;
  progress: number;
  input_hash: string;
  calibration_hash: string;
  parameter_hash: string;
  code_hash: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface QCResult {
  id: string;
  metric: string;
  value: number | null;
  threshold: number | null;
  passed: boolean;
  reason_code: string;
  details: Record<string, unknown>;
}

export interface LineageNode {
  id: string;
  kind: "PRODUCT" | "RAW_FILE";
  level: ProductLevel;
  schema_version?: string;
  sha256: string;
  qc_flag?: string;
  uri: string;
  exposure_id?: string;
}

export interface LineageEdge {
  source: string;
  target: string;
  relation: string;
  checksum: string;
}

export interface Lineage {
  root_id: string;
  nodes: LineageNode[];
  edges: LineageEdge[];
}

export interface Preview {
  product_id: string;
  level: ProductLevel;
  mode?: DataMode;
  shape?: number[];
  image?: number[][];
  columns?: Record<string, Array<number | null>>;
  metadata?: Record<string, unknown>;
  minimum?: number;
  maximum?: number;
  median?: number;
  saturated_fraction?: number;
}

export interface Alarm {
  id: string;
  severity: string;
  reason_code: string;
  message: string;
  protective_action: string;
  recovery_condition: string;
  acknowledged: boolean;
  created_at: string;
}

export interface StateEvent {
  cursor: number;
  event_id?: string;
  event_type: string;
  occurred_at: string;
  sequence_id?: string | null;
  exposure_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
  correlation_id: string;
  retryable: boolean;
}
