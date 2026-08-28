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
export type ImportStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
export type ProcessingStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_CALIBRATION"
  | "BLOCKED"
  | "SUCCEEDED"
  | "FAILED";
export type ConfigurationStatus = "UNVERIFIED" | "APPROVED" | "RETIRED";
export type QCFlag = "PASS" | "WARNING" | "FAIL" | "SIMULATION_ONLY";
export type PublicationStatus = "DRAFT" | "PUBLISHED" | "WITHDRAWN";

export interface CurrentUser {
  subject: string;
  display_name: string;
  role: Role;
  auth_mode: "dev" | "oidc";
}

export interface UserAccount {
  id: string;
  username: string;
  display_name: string;
  role: Role;
}

export interface AuthConfiguration {
  auth_mode: "dev" | "oidc";
  accounts: UserAccount[];
  default_account_id: string | null;
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
  size: number;
  sha256: string;
  schema_version: string;
  qc_flag: QCFlag;
  instrument: string | null;
  detector_profile: string | null;
  calibration_set_id: string | null;
  publication_status: PublicationStatus;
  download_url: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ProcessingRun {
  id: string;
  sequence_id: string;
  status: ProcessingStatus;
  progress: number;
  input_hash: string;
  calibration_hash: string;
  parameter_hash: string;
  code_hash: string;
  calibration_set_id: string | null;
  parameter_version: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type ProcessingStageKey = "l0" | "quicklook" | "l1" | "l2" | "l3";
export type ProcessingStageStatus =
  | "AVAILABLE"
  | "RUNNING"
  | "PENDING"
  | "PARTIAL"
  | "FAILED"
  | "BLOCKED"
  | "NOT_AVAILABLE";

export interface ProcessingStage {
  key: ProcessingStageKey;
  order: number;
  level: ProductLevel;
  status: ProcessingStageStatus;
  preview_kind: "image" | "spectrum";
  optional: boolean;
  expected_output_count: number;
  products: Product[];
}

export interface ImportInspectionRequest {
  root_id: string;
  relative_path: string;
  instrument: "ESPADONS";
}

export interface ImportInspection {
  id: string;
  root_id: string;
  relative_path: string;
  instrument: string;
  status: ImportStatus;
  manifest_sha256: string | null;
  inventory: Array<Record<string, unknown>>;
  groups: Array<Record<string, unknown>>;
  calibration_summary: Record<string, unknown>;
  warnings: Array<Record<string, unknown>>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportArtifactPreview {
  inspection_id: string;
  relative_path: string;
  role: string;
  detector?: string | null;
  shape: number[];
  preview_shape: number[];
  preview_reducer: string;
  image: Array<Array<number | null>>;
  order_annotations?: OrderAnnotation[];
  minimum: number;
  maximum: number;
  median: number;
}

export interface ImportBatch {
  id: string;
  inspection_id: string;
  manifest_sha256: string;
  status: ImportStatus;
  sequence_ids: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalibrationRun {
  id: string;
  import_batch_id: string;
  status: ProcessingStatus;
  progress: number;
  parameter_version: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalibrationSet {
  id: string;
  calibration_run_id: string;
  import_batch_id: string;
  instrument: string;
  detector: string;
  observing_night: string;
  readout_mode: string;
  status: ConfigurationStatus;
  calibration_hash: string;
  qc_flag: QCFlag;
  qc: Record<string, unknown>;
  warnings: Array<Record<string, unknown>>;
  approved_by: string | null;
  approved_at: string | null;
  approval_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessingRunRequest {
  sequence_id: string;
  calibration_set_id: string;
  parameter_version: string;
  parameters: Record<string, unknown>;
}

export interface ProcessingRunAccepted {
  processing_run_id: string;
  status: ProcessingStatus;
}

export interface DownloadedProduct {
  blob: Blob;
  filename: string;
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
  level?: ProductLevel;
  schema_version?: string;
  sha256: string;
  qc_flag?: string;
  download_url?: string | null;
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
  preview_shape?: number[];
  preview_reducer?: string;
  image?: Array<Array<number | null>>;
  order_annotations?: OrderAnnotation[];
  columns?: Record<string, Array<number | null>>;
  metadata?: Record<string, unknown>;
  minimum?: number;
  maximum?: number;
  median?: number;
  saturated_fraction?: number;
}

export interface OrderAnnotation {
  order: number;
  points: Array<[number, number]>;
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
