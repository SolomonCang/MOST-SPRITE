import type {
  AcceptedCommand,
  Alarm,
  ApiErrorBody,
  AuthConfiguration,
  CalibrationRun,
  CalibrationSet,
  CurrentUser,
  DownloadedProduct,
  Exposure,
  ImportArtifactPreview,
  ImportBatch,
  ImportInspection,
  ImportInspectionRequest,
  InstrumentSnapshot,
  Lineage,
  Preview,
  ProcessingRun,
  ProcessingRunAccepted,
  ProcessingRunRequest,
  ProcessingStage,
  Product,
  QCResult,
  Sequence,
  SequencePayload,
  SequenceValidation,
} from "./types";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const WS_URL = import.meta.env.VITE_WS_URL ?? API_URL.replace(/^http/, "ws");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiErrorBody,
  ) {
    super(body.message);
  }
}

export function makeIdempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const fallback: ApiErrorBody = {
      code: "HTTP_ERROR",
      message: response.statusText || "Request failed",
      details: {},
      correlation_id: response.headers.get("X-Correlation-ID") ?? "unknown",
      retryable: response.status >= 500,
    };
    const body = (await response.json().catch(() => fallback)) as ApiErrorBody;
    throw new ApiError(response.status, body);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function downloadFilename(response: Response, productId: string): string {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) return decodeURIComponent(encoded.replace(/^"|"$/g, ""));
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return plain ?? `${productId}.fits`;
}

async function downloadProduct(productId: string): Promise<DownloadedProduct> {
  const response = await fetch(`${API_URL}/api/v1/products/${productId}/download`, {
    credentials: "include",
  });
  if (!response.ok) {
    const fallback: ApiErrorBody = {
      code: "DOWNLOAD_FAILED",
      message: response.statusText || "Download failed",
      details: {},
      correlation_id: response.headers.get("X-Correlation-ID") ?? "unknown",
      retryable: response.status >= 500,
    };
    const body = (await response.json().catch(() => fallback)) as ApiErrorBody;
    throw new ApiError(response.status, body);
  }
  return {
    blob: await response.blob(),
    filename: downloadFilename(response, productId),
  };
}

export const api = {
  authConfiguration: () =>
    apiFetch<AuthConfiguration>("/api/v1/auth/configuration"),
  login: (accountId: string) =>
    apiFetch<CurrentUser>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId }),
    }),
  logout: () => apiFetch<void>("/api/v1/auth/logout", { method: "POST" }),
  me: () => apiFetch<CurrentUser>("/api/v1/me"),
  instrument: () => apiFetch<InstrumentSnapshot>("/api/v1/instrument/state"),
  alarms: () => apiFetch<Alarm[]>("/api/v1/alarms"),
  validateSequence: (payload: SequencePayload) =>
    apiFetch<SequenceValidation>("/api/v1/sequences:validate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createSequence: (payload: SequencePayload, key = makeIdempotencyKey("create")) =>
    apiFetch<AcceptedCommand>("/api/v1/sequences", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    }),
  sequenceAction: (
    sequenceId: string,
    action: "start" | "pause" | "resume" | "abort",
  ) =>
    apiFetch<AcceptedCommand>(`/api/v1/sequences/${sequenceId}:${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": makeIdempotencyKey(action) },
    }),
  sequences: () => apiFetch<Sequence[]>("/api/v1/sequences"),
  sequence: (id: string) => apiFetch<Sequence>(`/api/v1/sequences/${id}`),
  exposures: (id: string) =>
    apiFetch<Exposure[]>(`/api/v1/sequences/${id}/exposures`),
  products: (sequenceId?: string) =>
    apiFetch<Product[]>(
      `/api/v1/products${sequenceId ? `?sequence_id=${encodeURIComponent(sequenceId)}` : ""}`,
    ),
  product: (id: string) => apiFetch<Product>(`/api/v1/products/${id}`),
  processingRuns: () => apiFetch<ProcessingRun[]>("/api/v1/processing-runs"),
  processingRun: (id: string) =>
    apiFetch<ProcessingRun>(`/api/v1/processing-runs/${id}`),
  processingStages: (id: string) =>
    apiFetch<ProcessingStage[]>(`/api/v1/processing-runs/${id}/stages`),
  createProcessingRun: (
    payload: ProcessingRunRequest,
    key = makeIdempotencyKey("process"),
  ) =>
    apiFetch<ProcessingRunAccepted>("/api/v1/processing-runs", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    }),
  importInspections: () =>
    apiFetch<ImportInspection[]>("/api/v1/import-inspections"),
  importInspection: (id: string) =>
    apiFetch<ImportInspection>(`/api/v1/import-inspections/${id}`),
  importArtifactPreview: (inspectionId: string, relativePath: string) =>
    apiFetch<ImportArtifactPreview>(
      `/api/v1/import-inspections/${inspectionId}/preview?relative_path=${encodeURIComponent(relativePath)}`,
    ),
  createImportInspection: (
    payload: ImportInspectionRequest,
    key = makeIdempotencyKey("inspect"),
  ) =>
    apiFetch<ImportInspection>("/api/v1/import-inspections", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    }),
  imports: () => apiFetch<ImportBatch[]>("/api/v1/imports"),
  importBatch: (id: string) => apiFetch<ImportBatch>(`/api/v1/imports/${id}`),
  createImport: (
    inspection: Pick<ImportInspection, "id" | "manifest_sha256">,
    key = makeIdempotencyKey("import"),
  ) => {
    if (!inspection.manifest_sha256) throw new Error("Inspection has no manifest");
    return apiFetch<ImportBatch>("/api/v1/imports", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        inspection_id: inspection.id,
        manifest_sha256: inspection.manifest_sha256,
      }),
    });
  },
  calibrationRuns: () =>
    apiFetch<CalibrationRun[]>("/api/v1/calibration-runs"),
  calibrationRun: (id: string) =>
    apiFetch<CalibrationRun>(`/api/v1/calibration-runs/${id}`),
  createCalibrationRun: (
    importBatchId: string,
    parameterVersion: string,
    key = makeIdempotencyKey("calibrate"),
  ) =>
    apiFetch<CalibrationRun>("/api/v1/calibration-runs", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        import_batch_id: importBatchId,
        parameter_version: parameterVersion,
      }),
    }),
  calibrationSets: () => apiFetch<CalibrationSet[]>("/api/v1/calibration-sets"),
  calibrationSet: (id: string) =>
    apiFetch<CalibrationSet>(`/api/v1/calibration-sets/${id}`),
  approveCalibrationSet: (
    id: string,
    reason: string,
    acceptWarnings: boolean,
    key = makeIdempotencyKey("approve-calibration"),
  ) =>
    apiFetch<CalibrationSet>(`/api/v1/calibration-sets/${id}/approve`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ reason, accept_warnings: acceptWarnings }),
    }),
  preview: (id: string) => apiFetch<Preview>(`/api/v1/products/${id}/preview`),
  qc: (id: string) => apiFetch<QCResult[]>(`/api/v1/products/${id}/qc`),
  lineage: (id: string) => apiFetch<Lineage>(`/api/v1/products/${id}/lineage`),
  downloadProduct,
  productAction: (
    id: string,
    action: "publish" | "withdraw",
    reason: string | null,
    key = makeIdempotencyKey(action),
  ) =>
    apiFetch<Product>(`/api/v1/products/${id}:${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ reason }),
    }),
};
