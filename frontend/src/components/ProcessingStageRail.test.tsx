import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ProcessingStage } from "../lib/types";
import { renderWithPreferences } from "../test/render";
import { ProcessingStageRail } from "./ProcessingStageRail";

const stages: ProcessingStage[] = [
  {
    key: "l1",
    order: 3,
    level: "L1",
    status: "AVAILABLE",
    preview_kind: "image",
    optional: false,
    expected_output_count: 4,
    products: [{
      id: "product-1",
      processing_run_id: "run-1",
      sequence_id: "sequence-1",
      exposure_id: "exposure-1",
      level: "L1",
      mode: "POL_Q",
      size: 4096,
      sha256: "a".repeat(64),
      schema_version: "L1-v1",
      qc_flag: "PASS",
      instrument: "ESPADONS",
      detector_profile: "OLAPA",
      calibration_set_id: null,
      publication_status: "DRAFT",
      download_url: "/api/v1/products/product-1/download",
      metadata: {},
      created_at: "2026-08-27T00:00:00Z",
    }],
  },
];

describe("ProcessingStageRail", () => {
  it("links persisted stage outputs to their dedicated detail page", () => {
    renderWithPreferences(<MemoryRouter><ProcessingStageRail runId="run-1" stages={stages} /></MemoryRouter>);

    expect(screen.getByText("探测器校正")).toBeVisible();
    expect(screen.getByText("1 / 4 项产物")).toBeVisible();
    expect(screen.getByRole("link", { name: /探测器校正/ })).toHaveAttribute(
      "href",
      "/data/runs/run-1/stages/l1",
    );
  });
});
