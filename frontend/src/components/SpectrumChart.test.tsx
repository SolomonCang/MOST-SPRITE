import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithPreferences } from "../test/render";
import { SpectrumChart } from "./SpectrumChart";

describe("SpectrumChart", () => {
  it("plots the public P/N1/N2 contract", () => {
    const view = renderWithPreferences(
      <SpectrumChart
        columns={{
          WAVE: [500, 501, 700],
          ORDER: [42, 42, 41],
          P: [0.001, 0.002, 0.0015],
          N1: [0, 0.0001, 0],
          N2: [0, -0.0001, 0],
        }}
        series={["P", "N1", "N2"]}
      />,
    );
    expect(screen.getByRole("img", { name: /光谱产品预览/ })).toBeInTheDocument();
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(screen.getByText("N1")).toBeInTheDocument();
    expect(screen.getByText("N2")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /500\.00.*700\.00/ })).toBeInTheDocument();
    const polarizationPath = view.container.querySelector("path");
    expect(polarizationPath?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
  });

  it("shows a useful empty state for non-spectral products", () => {
    renderWithPreferences(<SpectrumChart series={["P"]} />);
    expect(screen.getByText("选择 L2 或 L3 产品查看科学光谱")).toBeInTheDocument();
  });
});
