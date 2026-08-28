import { fireEvent, screen } from "@testing-library/react";
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
    expect(screen.getByRole("img", { name: /数据产品预览/ })).toBeInTheDocument();
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(screen.getByText("N1")).toBeInTheDocument();
    expect(screen.getByText("N2")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /500\.00.*700\.00/ })).toBeInTheDocument();
    const polarizationPath = view.container.querySelector("path");
    expect(polarizationPath?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
  });

  it("shows a useful empty state for non-spectral products", () => {
    renderWithPreferences(<SpectrumChart series={["P"]} />);
    expect(screen.getByText("选择数据产品查看预览")).toBeInTheDocument();
  });

  it("zooms, resets, and exposes point inspection to the keyboard", () => {
    renderWithPreferences(
      <SpectrumChart
        columns={{
          WAVE: [500, 550, 600, 650, 700],
          P: [0.001, 0.0015, 0.002, 0.0016, 0.0012],
        }}
        series={["P"]}
        interactive
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "放大光谱" }));
    expect(screen.getByTestId("spectrum-range")).toHaveTextContent("550.00–650.00 nm");

    const chart = screen.getByRole("img", { name: /键盘加减号缩放/ });
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByText("550.0000 nm")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "复位光谱范围" }));
    expect(screen.getByTestId("spectrum-range")).toHaveTextContent("500.00–700.00 nm");
  });
});
