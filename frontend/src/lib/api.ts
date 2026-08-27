import type {
  AcceptedCommand,
  Alarm,
  ApiErrorBody,
  CurrentUser,
  Exposure,
  InstrumentSnapshot,
  Lineage,
  Preview,
  ProcessingRun,
  Product,
  QCResult,
  Sequence,
  SequencePayload,
  SequenceValidation,
} from "./types";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const WS_URL = import.meta.env.VITE_WS_URL ?? API_URL.replace(/^http/, "ws");

const identityHeaders = (): Record<string, string> => ({
  "X-SPRITE-User": import.meta.env.VITE_DEV_USER ?? "local-observer",
  "X-SPRITE-Role": import.meta.env.VITE_DEV_ROLE ?? "observer",
});

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
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...identityHeaders(),
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

export const api = {
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
  processingRuns: () => apiFetch<ProcessingRun[]>("/api/v1/processing-runs"),
  preview: (id: string) => apiFetch<Preview>(`/api/v1/products/${id}/preview`),
  qc: (id: string) => apiFetch<QCResult[]>(`/api/v1/products/${id}/qc`),
  lineage: (id: string) => apiFetch<Lineage>(`/api/v1/products/${id}/lineage`),
};
