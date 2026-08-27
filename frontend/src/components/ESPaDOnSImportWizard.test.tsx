import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import type {
  CalibrationRun,
  CalibrationSet,
  ImportBatch,
  ImportInspection,
  Sequence,
} from "../lib/types";
import { renderWithPreferences } from "../test/render";
import { ESPaDOnSImportWizard, countInventory } from "./ESPaDOnSImportWizard";

const createdAt = "2026-08-27T08:00:00Z";

describe("ESPaDOnSImportWizard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("counts the classified FITS inventory", () => {
    expect(countInventory([{ role: "SCIENCE" }, { role: "SCIENCE" }, { role: "THAR" }]))
      .toEqual({ SCIENCE: 2, THAR: 1 });
  });

  it("closes the inspect, import, calibrate, approve, and process workflow", async () => {
    const inspections: ImportInspection[] = [];
    const batches: ImportBatch[] = [];
    const runs: CalibrationRun[] = [];
    const sets: CalibrationSet[] = [];
    const sequence: Sequence = {
      id: "10000000-0000-4000-8000-000000000001",
      target_name: "AD Leo",
      mode: "POL_Q",
      exposure_time: 60,
      repeats: 1,
      expected_exposures: 4,
      completed_exposures: 4,
      attempt: 0,
      status: "SUCCEEDED",
      config_snapshot_id: "10000000-0000-4000-8000-000000000002",
      created_by: "reducer",
      last_error_code: null,
      last_error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const inspection: ImportInspection = {
      id: "20000000-0000-4000-8000-000000000001",
      root_id: "cadc-public",
      relative_path: "ad-leo",
      instrument: "ESPADONS",
      status: "SUCCEEDED",
      manifest_sha256: "a".repeat(64),
      inventory: [
        ...Array.from({ length: 4 }, () => ({ role: "SCIENCE" })),
        ...Array.from({ length: 10 }, () => ({ role: "FLAT" })),
        { role: "THAR" },
      ],
      groups: [{
        group_key: "2026-08-27:AD Leo:Q:1",
        target_name: "AD Leo",
        mode: "POL_Q",
        artifacts: ["q1.fits.fz", "q2.fits.fz", "q3.fits.fz", "q4.fits.fz"],
      }],
      calibration_summary: {},
      warnings: [{
        code: "FLAT_COUNT_BELOW_RECOMMENDED",
        message: "10 flats are accepted while 20 are recommended",
      }],
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const batch: ImportBatch = {
      id: "30000000-0000-4000-8000-000000000001",
      inspection_id: inspection.id,
      manifest_sha256: inspection.manifest_sha256!,
      status: "SUCCEEDED",
      sequence_ids: [sequence.id],
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const calibrationRun: CalibrationRun = {
      id: "40000000-0000-4000-8000-000000000001",
      import_batch_id: batch.id,
      status: "SUCCEEDED",
      progress: 1,
      parameter_version: "espadons-olapa-v1",
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const calibrationSet: CalibrationSet = {
      id: "50000000-0000-4000-8000-000000000001",
      calibration_run_id: calibrationRun.id,
      import_batch_id: batch.id,
      instrument: "ESPADONS",
      detector: "OLAPA",
      observing_night: "2026-08-27",
      readout_mode: "NORMAL",
      status: "UNVERIFIED",
      calibration_hash: "b".repeat(64),
      qc_flag: "WARNING",
      qc: {
        trace_rms_pixel: 0.023,
        alignment_valid_fraction: 0.995,
        wavelength: { wavelength_rms_m_s: 102.4 },
      },
      warnings: [{ code: "FLAT_COUNT_BELOW_RECOMMENDED" }],
      approved_by: null,
      approved_at: null,
      approval_reason: null,
      created_at: createdAt,
      updated_at: createdAt,
    };

    vi.spyOn(api, "importInspections").mockImplementation(async () => [...inspections]);
    vi.spyOn(api, "imports").mockImplementation(async () => [...batches]);
    vi.spyOn(api, "calibrationRuns").mockImplementation(async () => [...runs]);
    vi.spyOn(api, "calibrationSets").mockImplementation(async () => [...sets]);
    vi.spyOn(api, "sequences").mockResolvedValue([sequence]);
    vi.spyOn(api, "processingRuns").mockResolvedValue([]);
    vi.spyOn(api, "createImportInspection").mockImplementation(async () => {
      inspections.unshift(inspection);
      return inspection;
    });
    vi.spyOn(api, "createImport").mockImplementation(async () => {
      batches.unshift(batch);
      return batch;
    });
    vi.spyOn(api, "createCalibrationRun").mockImplementation(async () => {
      runs.unshift(calibrationRun);
      sets.unshift(calibrationSet);
      return calibrationRun;
    });
    vi.spyOn(api, "approveCalibrationSet").mockImplementation(async () => {
      calibrationSet.status = "APPROVED";
      calibrationSet.approved_by = "admin";
      return calibrationSet;
    });
    const createProcessingRun = vi.spyOn(api, "createProcessingRun").mockResolvedValue({
      processing_run_id: "60000000-0000-4000-8000-000000000001",
      status: "QUEUED",
    });
    const onSequenceSelect = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    renderWithPreferences(
      <QueryClientProvider client={queryClient}>
        <ESPaDOnSImportWizard
          user={{
            subject: "admin",
            display_name: "Administrator",
            role: "administrator",
            auth_mode: "dev",
          }}
          onSequenceSelect={onSequenceSelect}
        />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("导入根目录标识"), {
      target: { value: "cadc-public" },
    });
    fireEvent.change(screen.getByLabelText("相对路径"), { target: { value: "ad-leo" } });
    fireEvent.click(screen.getByRole("button", { name: "检查目录" }));
    expect(await screen.findByText("POL_Q · AD Leo · 4/4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "校验清单并导入" }));
    expect(await screen.findByText("生成 1 个偏振序列")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "构建 CalibrationSet" }));
    expect(await screen.findByText("0.0230 px")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("审批理由"), {
      target: { value: "公开数据科学回归质控通过" },
    });
    fireEvent.click(screen.getByLabelText("我已检查并接受此 CalibrationSet 的全部警告"));
    fireEvent.click(screen.getByRole("button", { name: "批准 CalibrationSet" }));
    expect(await screen.findByText("已由 admin 审批，可用于正式处理")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "处理选中的 1 个序列" }));
    await waitFor(() => expect(createProcessingRun).toHaveBeenCalledWith(expect.objectContaining({
      sequence_id: sequence.id,
      calibration_set_id: calibrationSet.id,
      parameter_version: "espadons-olapa-v1",
    })));
    expect(onSequenceSelect).toHaveBeenCalledWith(sequence.id);
  });

  it("resumes a persisted calibration and processing run after reload", async () => {
    const inspection: ImportInspection = {
      id: "21000000-0000-4000-8000-000000000001",
      root_id: "cadc-public",
      relative_path: "night/hd-236928",
      instrument: "ESPADONS",
      status: "SUCCEEDED",
      manifest_sha256: "c".repeat(64),
      inventory: [{ role: "SCIENCE" }],
      groups: [{
        group_key: "HD-Q",
        target_name: "HD 236928",
        mode: "POL_Q",
        artifacts: ["1", "2", "3", "4"],
      }],
      calibration_summary: {},
      warnings: [],
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const batch: ImportBatch = {
      id: "31000000-0000-4000-8000-000000000001",
      inspection_id: inspection.id,
      manifest_sha256: inspection.manifest_sha256!,
      status: "SUCCEEDED",
      sequence_ids: ["11000000-0000-4000-8000-000000000001"],
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const calibrationRun: CalibrationRun = {
      id: "41000000-0000-4000-8000-000000000001",
      import_batch_id: batch.id,
      status: "RUNNING",
      progress: 0.42,
      parameter_version: "espadons-olapa-v1",
      error_code: null,
      error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };
    const sequence: Sequence = {
      id: batch.sequence_ids[0],
      target_name: "HD 236928",
      mode: "POL_Q",
      exposure_time: 300,
      repeats: 1,
      expected_exposures: 4,
      completed_exposures: 4,
      attempt: 0,
      status: "SUCCEEDED",
      config_snapshot_id: "11000000-0000-4000-8000-000000000002",
      created_by: "reducer",
      last_error_code: null,
      last_error_message: null,
      created_at: createdAt,
      updated_at: createdAt,
    };

    vi.spyOn(api, "importInspections").mockResolvedValue([inspection]);
    vi.spyOn(api, "imports").mockResolvedValue([batch]);
    vi.spyOn(api, "calibrationRuns").mockResolvedValue([calibrationRun]);
    vi.spyOn(api, "calibrationSets").mockResolvedValue([]);
    vi.spyOn(api, "sequences").mockResolvedValue([sequence]);
    vi.spyOn(api, "processingRuns").mockResolvedValue([]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    renderWithPreferences(
      <QueryClientProvider client={queryClient}>
        <ESPaDOnSImportWizard
          user={{
            subject: "reducer",
            display_name: "Reducer",
            role: "data_reducer",
            auth_mode: "dev",
          }}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("恢复已有检查")).toHaveValue(inspection.id);
    expect(await screen.findByText("POL_Q · HD 236928 · 4/4")).toBeInTheDocument();
    expect(await screen.findByText("42%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "标定已构建" })).toBeDisabled();
  });
});
