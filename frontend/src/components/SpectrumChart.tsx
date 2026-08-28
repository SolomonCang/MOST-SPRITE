import { Minus, Plus, RotateCcw } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useI18n } from "../i18n/I18nProvider";

interface SpectrumChartProps {
  columns?: Record<string, Array<number | null>>;
  series: string[];
  compact?: boolean;
  interactive?: boolean;
}

interface ViewDomain {
  minimum: number;
  maximum: number;
}

const PLOT_LEFT = 68;
const PLOT_RIGHT = 758;
const PLOT_TOP = 24;
const PLOT_BOTTOM = 232;
const MIN_ZOOM_WINDOW = 1 / 128;

const colors: Record<string, string> = {
  I: "var(--chart-primary)",
  P: "var(--chart-warning)",
  N1: "var(--chart-violet)",
  N2: "var(--chart-success)",
  TARGET: "var(--chart-primary)",
  SKY: "var(--chart-violet)",
  ALPHA: "var(--chart-warning)",
  FLUX: "var(--chart-primary)",
  VAR: "var(--chart-warning)",
  ERR_I: "var(--chart-warning)",
  ERR_P: "var(--chart-warning)",
  ERR_N1: "var(--chart-violet)",
  ERR_N2: "var(--chart-success)",
  ERR_TARGET: "var(--chart-primary)",
  ERR_SKY: "var(--chart-violet)",
};

function finiteExtent(values: Array<number | null>): ViewDomain | null {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (value === null || !Number.isFinite(value)) continue;
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
  }
  return Number.isFinite(minimum) && Number.isFinite(maximum) ? { minimum, maximum } : null;
}

function normalizeView(view: ViewDomain, full: ViewDomain): ViewDomain {
  const fullRange = full.maximum - full.minimum;
  const minimumRange = fullRange * MIN_ZOOM_WINDOW;
  const requestedRange = Math.min(fullRange, Math.max(minimumRange, view.maximum - view.minimum));
  let minimum = view.minimum;
  let maximum = minimum + requestedRange;
  if (minimum < full.minimum) {
    minimum = full.minimum;
    maximum = minimum + requestedRange;
  }
  if (maximum > full.maximum) {
    maximum = full.maximum;
    minimum = maximum - requestedRange;
  }
  return { minimum, maximum };
}

export function SpectrumChart({ columns, series, compact = false, interactive = false }: SpectrumChartProps) {
  const { t } = useI18n();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ pointerId: number; lastClientX: number } | null>(null);
  const clipId = `spectrum-clip-${useId().replace(/:/g, "")}`;
  const seriesKey = series.join("|");
  const [viewState, setViewState] = useState<ViewDomain | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const prepared = useMemo(() => {
    if (!columns) return null;
    const selected = series.filter((name) => columns[name]?.length);
    if (!selected.length) return null;
    const length = Math.min(...selected.map((name) => columns[name].length));
    if (!length) return null;
    const hasFiniteSeries = selected.some((name) => finiteExtent(columns[name].slice(0, length)) !== null);
    if (!hasFiniteSeries) return null;

    const wavelengthColumn = (columns.WAVE ?? []).slice(0, length);
    const wavelengthExtent = finiteExtent(wavelengthColumn);
    const usesWavelength = wavelengthColumn.length === length
      && wavelengthExtent !== null
      && wavelengthExtent.maximum > wavelengthExtent.minimum;
    const xValues = Array.from({ length }, (_, index) => {
      const wavelength = wavelengthColumn[index];
      return usesWavelength && wavelength !== null && Number.isFinite(wavelength) ? wavelength : usesWavelength ? null : index;
    });
    const fullView = usesWavelength && wavelengthExtent
      ? wavelengthExtent
      : { minimum: 0, maximum: Math.max(1, length - 1) };

    return {
      selected,
      length,
      xValues,
      fullView,
      orders: (columns.ORDER ?? []).slice(0, length),
    };
  }, [columns, seriesKey]);

  useEffect(() => {
    setViewState(null);
    setSelectedIndex(null);
  }, [columns, seriesKey]);

  const activeView = useMemo(() => {
    if (!prepared) return null;
    return normalizeView(viewState ?? prepared.fullView, prepared.fullView);
  }, [prepared, viewState]);

  const updateView = useCallback((transform: (current: ViewDomain) => ViewDomain) => {
    if (!prepared) return;
    setViewState((current) => normalizeView(transform(normalizeView(current ?? prepared.fullView, prepared.fullView)), prepared.fullView));
  }, [prepared]);

  const zoom = useCallback((factor: number, center?: number) => {
    if (!activeView) return;
    updateView((current) => {
      const anchor = center ?? (current.minimum + current.maximum) / 2;
      const nextRange = (current.maximum - current.minimum) * factor;
      const ratio = (anchor - current.minimum) / Math.max(Number.EPSILON, current.maximum - current.minimum);
      return {
        minimum: anchor - nextRange * ratio,
        maximum: anchor + nextRange * (1 - ratio),
      };
    });
  }, [activeView, updateView]);

  const pan = useCallback((amount: number) => {
    updateView((current) => ({ minimum: current.minimum + amount, maximum: current.maximum + amount }));
  }, [updateView]);

  const resetView = useCallback(() => {
    setViewState(null);
  }, []);

  const clientXToData = useCallback((clientX: number): number | null => {
    if (!activeView || !svgRef.current) return null;
    const bounds = svgRef.current.getBoundingClientRect();
    if (!bounds.width) return null;
    const svgX = ((clientX - bounds.left) / bounds.width) * 800;
    const ratio = Math.max(0, Math.min(1, (svgX - PLOT_LEFT) / (PLOT_RIGHT - PLOT_LEFT)));
    return activeView.minimum + ratio * (activeView.maximum - activeView.minimum);
  }, [activeView]);

  const visibleIndices = useMemo(() => {
    if (!prepared || !activeView || !columns) return [];
    const indices: number[] = [];
    for (let index = 0; index < prepared.length; index += 1) {
      const x = prepared.xValues[index];
      if (x === null || x < activeView.minimum || x > activeView.maximum) continue;
      if (prepared.selected.some((name) => {
        const value = columns[name][index];
        return value !== null && Number.isFinite(value);
      })) indices.push(index);
    }
    return indices;
  }, [activeView, columns, prepared]);

  const selectNearest = useCallback((xValue: number) => {
    if (!prepared || !visibleIndices.length) return;
    let closestIndex = visibleIndices[0];
    let closestDistance = Math.abs((prepared.xValues[closestIndex] ?? xValue) - xValue);
    for (const index of visibleIndices.slice(1)) {
      const distance = Math.abs((prepared.xValues[index] ?? xValue) - xValue);
      if (distance < closestDistance) {
        closestIndex = index;
        closestDistance = distance;
      }
    }
    setSelectedIndex(closestIndex);
  }, [prepared, visibleIndices]);

  useEffect(() => {
    const node = svgRef.current;
    if (!node || !interactive) return;
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const center = clientXToData(event.clientX);
      zoom(Math.exp(Math.max(-600, Math.min(600, event.deltaY)) * 0.0015), center ?? undefined);
    };
    node.addEventListener("wheel", handleWheel, { passive: false });
    return () => node.removeEventListener("wheel", handleWheel);
  }, [clientXToData, interactive, zoom]);

  const chart = useMemo(() => {
    if (!prepared || !activeView || !columns) return null;
    let minimum = Number.POSITIVE_INFINITY;
    let maximum = Number.NEGATIVE_INFINITY;
    for (const name of prepared.selected) {
      for (let index = 0; index < prepared.length; index += 1) {
        const x = prepared.xValues[index];
        const value = columns[name][index];
        if (x === null || x < activeView.minimum || x > activeView.maximum || value === null || !Number.isFinite(value)) continue;
        minimum = Math.min(minimum, value);
        maximum = Math.max(maximum, value);
      }
    }
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
      for (const name of prepared.selected) {
        const extent = finiteExtent(columns[name].slice(0, prepared.length));
        if (!extent) continue;
        minimum = Math.min(minimum, extent.minimum);
        maximum = Math.max(maximum, extent.maximum);
      }
    }
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return null;
    if (minimum === maximum) {
      minimum -= 1;
      maximum += 1;
    } else {
      const padding = (maximum - minimum) * 0.04;
      minimum -= padding;
      maximum += padding;
    }

    const xScale = (value: number) => PLOT_LEFT + ((value - activeView.minimum) / Math.max(Number.EPSILON, activeView.maximum - activeView.minimum)) * (PLOT_RIGHT - PLOT_LEFT);
    const yScale = (value: number) => PLOT_TOP + (1 - (value - minimum) / (maximum - minimum)) * (PLOT_BOTTOM - PLOT_TOP);
    const paths = prepared.selected.map((name) => {
      const segments: string[] = [];
      let penDown = false;
      columns[name].slice(0, prepared.length).forEach((value, index) => {
        const xValue = prepared.xValues[index];
        if (
          value === null
          || !Number.isFinite(value)
          || xValue === null
          || xValue < activeView.minimum
          || xValue > activeView.maximum
        ) {
          penDown = false;
          return;
        }
        if (index > 0 && prepared.orders.length && prepared.orders[index] !== prepared.orders[index - 1]) penDown = false;
        segments.push(`${penDown ? "L" : "M"}${xScale(xValue).toFixed(2)},${yScale(value).toFixed(2)}`);
        penDown = true;
      });
      return { name, path: segments.join(" ") };
    });
    return { minimum, maximum, paths, xScale, yScale };
  }, [activeView, columns, prepared]);

  const selection = useMemo(() => {
    if (selectedIndex === null || !prepared || !columns || !activeView) return null;
    const x = prepared.xValues[selectedIndex];
    if (x === null || x < activeView.minimum || x > activeView.maximum) return null;
    return {
      x,
      values: prepared.selected.map((name) => ({ name, value: columns[name][selectedIndex] })).filter((item): item is { name: string; value: number } => item.value !== null && Number.isFinite(item.value)),
    };
  }, [activeView, columns, prepared, selectedIndex]);

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!interactive || event.button !== 0) return;
    dragRef.current = { pointerId: event.pointerId, lastClientX: event.clientX };
    event.currentTarget.setPointerCapture(event.pointerId);
    const x = clientXToData(event.clientX);
    if (x !== null) selectNearest(x);
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!interactive) return;
    const drag = dragRef.current;
    if (drag?.pointerId === event.pointerId && activeView && svgRef.current) {
      const bounds = svgRef.current.getBoundingClientRect();
      if (bounds.width) {
        const delta = -((event.clientX - drag.lastClientX) / bounds.width) * (activeView.maximum - activeView.minimum);
        if (Math.abs(event.clientX - drag.lastClientX) > 0) pan(delta);
      }
      drag.lastClientX = event.clientX;
      return;
    }
    const x = clientXToData(event.clientX);
    if (x !== null) selectNearest(x);
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const handleKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    if (!interactive || !activeView) return;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoom(0.5, selection?.x);
      return;
    }
    if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoom(2, selection?.x);
      return;
    }
    if (event.key === "Home" || event.key === "0") {
      event.preventDefault();
      resetView();
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    if (event.shiftKey) {
      pan(direction * (activeView.maximum - activeView.minimum) * 0.12);
      return;
    }
    if (!visibleIndices.length) return;
    const position = selectedIndex === null ? -1 : visibleIndices.indexOf(selectedIndex);
    const nextPosition = position < 0
      ? (direction > 0 ? 0 : visibleIndices.length - 1)
      : Math.max(0, Math.min(visibleIndices.length - 1, position + direction));
    setSelectedIndex(visibleIndices[nextPosition]);
  };

  if (!prepared || !activeView || !chart) return <div className="chart-empty">{t("data.preview.empty")}</div>;
  const zoomLevel = (prepared.fullView.maximum - prepared.fullView.minimum) / Math.max(Number.EPSILON, activeView.maximum - activeView.minimum);
  const isZoomed = zoomLevel > 1.001;
  const summary = t("data.preview.range", {
    series: chart.paths.map((path) => path.name).join(", "),
    xMin: activeView.minimum.toFixed(2),
    xMax: activeView.maximum.toFixed(2),
    yMin: chart.minimum.toExponential(2),
    yMax: chart.maximum.toExponential(2),
  });

  return (
    <figure className={`spectrum-wrap ${compact ? "spectrum-compact" : ""} ${interactive ? "spectrum-interactive" : ""}`}>
      {interactive && (
        <div className="spectrum-toolbar" aria-label={t("data.preview.zoomControls")}>
          <div className="spectrum-range" data-testid="spectrum-range">
            <span>{t("data.preview.visibleRange")}</span>
            <strong>{activeView.minimum.toFixed(2)}–{activeView.maximum.toFixed(2)} {t("data.preview.xUnitShort")}</strong>
            <small>{zoomLevel.toFixed(1)}×</small>
          </div>
          <div className="spectrum-toolbar-buttons">
            <button type="button" onClick={() => zoom(0.5, selection?.x)} aria-label={t("data.preview.zoomIn")} title={t("data.preview.zoomIn")}><Plus size={15} /></button>
            <button type="button" onClick={() => zoom(2, selection?.x)} disabled={!isZoomed} aria-label={t("data.preview.zoomOut")} title={t("data.preview.zoomOut")}><Minus size={15} /></button>
            <button type="button" onClick={resetView} disabled={!isZoomed} aria-label={t("data.preview.zoomReset")} title={t("data.preview.zoomReset")}><RotateCcw size={14} /></button>
          </div>
        </div>
      )}
      <svg
        ref={svgRef}
        className="spectrum-chart"
        viewBox="0 0 800 286"
        role="img"
        aria-label={`${t("data.preview.aria")}. ${summary}${interactive ? `. ${t("data.preview.keyboardHelp")}` : ""}`}
        tabIndex={interactive ? 0 : undefined}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onKeyDown={handleKeyDown}
      >
        <defs><clipPath id={clipId}><rect x={PLOT_LEFT} y={PLOT_TOP} width={PLOT_RIGHT - PLOT_LEFT} height={PLOT_BOTTOM - PLOT_TOP} rx="6" /></clipPath></defs>
        <rect x={PLOT_LEFT} y={PLOT_TOP} width={PLOT_RIGHT - PLOT_LEFT} height={PLOT_BOTTOM - PLOT_TOP} rx="6" className="chart-plot" />
        {[0, 1, 2, 3, 4].map((line) => {
          const y = PLOT_TOP + line * ((PLOT_BOTTOM - PLOT_TOP) / 4);
          const value = chart.maximum - (line / 4) * (chart.maximum - chart.minimum);
          return <g key={line}><line x1={PLOT_LEFT} x2={PLOT_RIGHT} y1={y} y2={y} className="chart-grid" /><text x="58" y={y + 3} textAnchor="end" className="chart-label">{value.toExponential(1)}</text></g>;
        })}
        <g clipPath={`url(#${clipId})`}>
          {chart.paths.map(({ name, path }) => <path key={name} d={path} fill="none" stroke={colors[name] ?? "var(--color-ink)"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />)}
          {selection && selection.x >= activeView.minimum && selection.x <= activeView.maximum && (
            <g className="chart-cursor">
              <line x1={chart.xScale(selection.x)} x2={chart.xScale(selection.x)} y1={PLOT_TOP} y2={PLOT_BOTTOM} />
              {selection.values.map(({ name, value }) => <circle key={name} cx={chart.xScale(selection.x)} cy={chart.yScale(value)} r="3.5" fill={colors[name] ?? "var(--color-ink)"} />)}
            </g>
          )}
        </g>
        <text x={PLOT_LEFT} y="252" className="chart-label">{activeView.minimum.toFixed(2)}</text>
        <text x={PLOT_RIGHT} y="252" textAnchor="end" className="chart-label">{activeView.maximum.toFixed(2)}</text>
        <text x="413" y="276" textAnchor="middle" className="chart-axis-label">{t("data.preview.xAxis")} · {t("data.preview.xUnit")}</text>
        <text x="14" y="128" textAnchor="middle" className="chart-axis-label" transform="rotate(-90 14 128)">{t("data.preview.yAxis")}</text>
      </svg>
      <figcaption className="chart-legend">
        {chart.paths.map(({ name }) => <span key={name}><i style={{ background: colors[name] ?? "var(--color-ink)" }} />{name}</span>)}
      </figcaption>
      {interactive && (
        <div className="spectrum-inspector">
          <span>{t("data.preview.cursorReadout")}</span>
          {selection
            ? <output><strong>{selection.x.toFixed(4)} {t("data.preview.xUnitShort")}</strong>{selection.values.map(({ name, value }) => <span key={name}>{name} <b>{value.toExponential(5)}</b></span>)}</output>
            : <small>{t("data.preview.interactionHelp")}</small>}
        </div>
      )}
      <p className="visually-hidden">{summary}</p>
    </figure>
  );
}
