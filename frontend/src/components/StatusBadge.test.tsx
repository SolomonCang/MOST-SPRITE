import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders a successful state with the good tone", () => {
    render(<StatusBadge value="SUCCEEDED" />);
    expect(screen.getByText("SUCCEEDED")).toHaveClass("status-good");
  });

  it("renders simulation state as a warning", () => {
    render(<StatusBadge value="SIMULATION_ONLY" subtle />);
    expect(screen.getByText("SIMULATION ONLY")).toHaveClass("status-warn", "status-subtle");
  });
});
