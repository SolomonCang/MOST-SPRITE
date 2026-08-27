import { describe, expect, it } from "vitest";
import { rasterizeImage } from "./Heatmap";

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
});
