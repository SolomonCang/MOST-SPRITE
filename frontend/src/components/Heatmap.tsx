import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../i18n/I18nProvider";

type ScaleMode = "log" | "linear";

interface HeatmapProps {
  values?: Array<Array<number | null>>;
  label?: string;
  emptyLabel: string;
  scaleLabel: string;
  unit: string;
  defaultScale?: ScaleMode;
}

interface RasterizedImage {
  pixels: Uint8ClampedArray;
  rows: number;
  columns: number;
  lower: number;
  upper: number;
}

function quantile(sorted: number[], ratio: number): number {
  if (sorted.length === 1) return sorted[0];
  const position = (sorted.length - 1) * ratio;
  const lowerIndex = Math.floor(position);
  const fraction = position - lowerIndex;
  const upperValue = sorted[Math.min(sorted.length - 1, lowerIndex + 1)];
  return sorted[lowerIndex] + (upperValue - sorted[lowerIndex]) * fraction;
}

export function rasterizeImage(values: Array<Array<number | null>>, mode: ScaleMode): RasterizedImage | null {
  const rows = values.length;
  const columns = values[0]?.length ?? 0;
  if (!rows || !columns) return null;

  const finite: number[] = [];
  for (const row of values) {
    for (const value of row) {
      if (value !== null && Number.isFinite(value)) finite.push(value);
    }
  }
  if (!finite.length) return null;
  finite.sort((left, right) => left - right);
  let lower = quantile(finite, 0.01);
  let upper = quantile(finite, 0.997);
  if (!(upper > lower)) {
    lower = finite[0];
    upper = finite[finite.length - 1];
  }
  const span = upper > lower ? upper - lower : 1;
  const logDenominator = Math.log1p(1000);
  const pixels = new Uint8ClampedArray(rows * columns * 4);

  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < columns; x += 1) {
      const value = values[y]?.[x];
      const offset = (y * columns + x) * 4;
      const ratio = value === null || !Number.isFinite(value)
        ? 0
        : Math.max(0, Math.min(1, (value - lower) / span));
      const stretched = mode === "log" ? Math.log1p(1000 * ratio) / logDenominator : ratio;
      const intensity = Math.round(stretched * 255);
      pixels[offset] = intensity;
      pixels[offset + 1] = intensity;
      pixels[offset + 2] = intensity;
      pixels[offset + 3] = 255;
    }
  }

  return { pixels, rows, columns, lower, upper };
}

export function Heatmap({ values, label = "CCD quicklook image", emptyLabel, scaleLabel, unit, defaultScale = "log" }: HeatmapProps) {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [scaleMode, setScaleMode] = useState<ScaleMode>(defaultScale);
  const raster = useMemo(() => values ? rasterizeImage(values, scaleMode) : null, [scaleMode, values]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !raster) return;
    const source = document.createElement("canvas");
    source.width = raster.columns;
    source.height = raster.rows;
    const sourceContext = source.getContext("2d");
    if (!sourceContext) return;
    const imageData = sourceContext.createImageData(raster.columns, raster.rows);
    imageData.data.set(raster.pixels);
    sourceContext.putImageData(imageData, 0, 0);

    const draw = () => {
      const width = canvas.parentElement?.clientWidth ?? raster.columns;
      const height = canvas.parentElement?.clientHeight ?? raster.rows;
      const pixelRatio = Math.min(globalThis.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(width * pixelRatio));
      canvas.height = Math.max(1, Math.round(height * pixelRatio));
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.fillStyle = "#000";
      context.fillRect(0, 0, width, height);
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
      context.drawImage(source, 0, 0, width, height);
    };

    draw();
    if (typeof ResizeObserver === "undefined") {
      globalThis.addEventListener("resize", draw);
      return () => globalThis.removeEventListener("resize", draw);
    }
    const observer = new ResizeObserver(draw);
    observer.observe(canvas.parentElement ?? canvas);
    return () => observer.disconnect();
  }, [raster]);

  if (!raster) return <div className="heatmap-empty">{emptyLabel}</div>;

  return (
    <div className="heatmap-figure">
      <div className="heatmap-toolbar">
        <span>{t("data.image.percentileRange")}</span>
        <div className="heatmap-scale-switch" role="group" aria-label={t("data.image.scaleMode")}>
          <button type="button" aria-pressed={scaleMode === "log"} onClick={() => setScaleMode("log")}>{t("data.image.log")}</button>
          <button type="button" aria-pressed={scaleMode === "linear"} onClick={() => setScaleMode("linear")}>{t("data.image.linear")}</button>
        </div>
      </div>
      <div
        className="heatmap"
        role="img"
        aria-label={`${label}; ${scaleMode} scale; display range ${raster.lower.toFixed(1)} to ${raster.upper.toFixed(1)} ${unit}`}
        style={{ aspectRatio: `${raster.columns} / ${raster.rows}` }}
      >
        <canvas ref={canvasRef} data-testid="heatmap-canvas" aria-hidden="true" />
      </div>
      <div className="heatmap-scale"><span>{raster.lower.toFixed(0)}</span><i /><span>{raster.upper.toFixed(0)} {unit}</span><b>{scaleMode === "log" ? scaleLabel : t("data.image.linearIntensity")}</b></div>
    </div>
  );
}
