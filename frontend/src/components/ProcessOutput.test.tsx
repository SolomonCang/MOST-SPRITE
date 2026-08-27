import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StateEvent } from "../lib/types";
import { renderWithPreferences } from "../test/render";
import { ProcessOutput } from "./ProcessOutput";

const event: StateEvent = {
  cursor: 42,
  event_id: "event-42",
  event_type: "exposure.committed.v1",
  occurred_at: "2026-08-27T12:34:56Z",
  sequence_id: "sequence-12345678",
  payload: { status: "COMMITTED", sub_index: 4 },
};

describe("ProcessOutput", () => {
  it("shows live metrics and structured process events", () => {
    renderWithPreferences(<ProcessOutput events={[event]} connected metrics={[{ label: "L0", value: "4" }]} />);
    expect(screen.getByText("实时运行记录")).toBeInTheDocument();
    expect(screen.getByText("在线")).toBeInTheDocument();
    expect(screen.getByText("exposure.committed.v1")).toBeInTheDocument();
    expect(screen.getByText("status=COMMITTED · sub_index=4")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("keeps a visible reconnecting empty state", () => {
    renderWithPreferences(<ProcessOutput events={[]} connected={false} emptyLabel="等待工程反馈" />);
    expect(screen.getByText("重连中")).toBeInTheDocument();
    expect(screen.getByText("等待工程反馈")).toBeInTheDocument();
  });
});
