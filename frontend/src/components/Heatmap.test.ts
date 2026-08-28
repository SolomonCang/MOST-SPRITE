import { screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithPreferences } from "../test/render";
import { Heatmap, rasterizeImage } from "./Heatmap";

describe("rasterizeImage", () => {
  it("uses a grayscale log stretch that reveals faint structure", () => {
    const values = [[0, 1, 10, 100, 1000, null]];
    const logarithmic = rasterizeImage(values, "log");
    const linear = rasterizeImage(values, "linear");

    expect(logarithmic).not.toBeNull();
    expect(linear).not.toBeNull();
    expect(logarithmic!.pixels[4]).toBeGreaterThan(linear!.pixels[4]);
    expect(logarithmic!.pixels[8]).toBeGreaterThan(linear!.pixels[8]);
    expect(logarithmic!.pixels[8]).toBe(logarithmic!.pixels[9]);
    expect(logarithmic!.pixels[9]).toBe(logarithmic!.pixels[10]);
    expect(logarithmic!.pixels[11]).toBe(255);
    expect(logarithmic!.pixels[20]).toBe(0);
  });

  it("returns null when no finite image data exists", () => {
    expect(rasterizeImage([[null, Number.NaN]], "log")).toBeNull();
  });

  it("renders a trace and label for every recognized order", () => {
    const context = {
      createImageData: (width: number, height: number) => ({
        data: new Uint8ClampedArray(width * height * 4),
      }),
      putImageData: vi.fn(),
      setTransform: vi.fn(),
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    };
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(context as unknown as CanvasRenderingContext2D);

    renderWithPreferences(createElement(Heatmap, {
      values: [[1, 2], [3, 4]],
      emptyLabel: "empty",
      scaleLabel: "log",
      unit: "ADU",
      orderAnnotations: [22, 23, 24].map((order, index) => ({
        order,
        points: [
          [0, 0.2 + index * 0.2] as [number, number],
          [1, 0.2 + index * 0.2] as [number, number],
        ],
      })),
    }));

    const overlay = screen.getByTestId("heatmap-order-overlay");
    expect(overlay.querySelectorAll("polyline")).toHaveLength(3);
    expect(overlay.querySelectorAll("span")).toHaveLength(3);
    expect(overlay).toHaveTextContent("m=22");
    expect(overlay).toHaveTextContent("m=24");
    expect(screen.getByText("已标注 3 个级次")).toBeInTheDocument();
    getContext.mockRestore();
  });
});
