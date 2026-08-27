import { useMemo } from "react";
import { useI18n } from "../i18n/I18nProvider";

interface SpectrumChartProps {
  columns?: Record<string, Array<number | null>>;
  series: string[];
  compact?: boolean;
}

const colors: Record<string, string> = {
  I: "var(--chart-primary)",
  P: "var(--chart-warning)",
  N1: "var(--chart-violet)",
  N2: "var(--chart-success)",
  TARGET: "var(--chart-primary)",
  SKY: "var(--chart-violet)",
  ALPHA: "var(--chart-warning)",
  FLUX: "var(--chart-primary)",
};

function finiteValues(values: Array<number | null>): number[] {
  return values.filter((value): value is number => value !== null && Number.isFinite(value));
}

export function SpectrumChart({ columns, series, compact = false }: SpectrumChartProps) {
  const { t } = useI18n();
  const chart = useMemo(() => {
    if (!columns) return null;
    const selected = series.filter((name) => columns[name]?.length);
    if (!selected.length) return null;
    const length = Math.min(...selected.map((name) => columns[name].length));
    const finite = selected.flatMap((name) => finiteValues(columns[name].slice(0, length)));
    if (!finite.length) return null;
    let minimum = Math.min(...finite);
    let maximum = Math.max(...finite);
    if (minimum === maximum) {
      minimum -= 1;
      maximum += 1;
    }
    const paths = selected.map((name) => {
      const segments: string[] = [];
      let penDown = false;
      columns[name].slice(0, length).forEach((value, index) => {
        if (value === null || !Number.isFinite(value)) {
          penDown = false;
          return;
        }
        const x = 68 + (index / Math.max(1, length - 1)) * 690;
        const y = 24 + (1 - (value - minimum) / (maximum - minimum)) * 208;
        segments.push(`${penDown ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`);
        penDown = true;
      });
      return { name, path: segments.join(" ") };
    });
    const wavelength = finiteValues((columns.WAVE ?? []).slice(0, length));
    return {
      minimum,
      maximum,
      paths,
      xMinimum: wavelength.length ? Math.min(...wavelength) : 0,
      xMaximum: wavelength.length ? Math.max(...wavelength) : Math.max(0, length - 1),
    };
  }, [columns, series]);

  if (!chart) return <div className="chart-empty">{t("data.preview.empty")}</div>;
  const summary = t("data.preview.range", {
    series: chart.paths.map((path) => path.name).join(", "),
    xMin: chart.xMinimum.toFixed(2),
    xMax: chart.xMaximum.toFixed(2),
    yMin: chart.minimum.toExponential(2),
    yMax: chart.maximum.toExponential(2),
  });

  return (
    <figure className={`spectrum-wrap ${compact ? "spectrum-compact" : ""}`}>
      <svg className="spectrum-chart" viewBox="0 0 800 286" role="img" aria-label={`${t("data.preview.aria")}. ${summary}`}>
        <rect x="68" y="24" width="690" height="208" rx="6" className="chart-plot" />
        {[0, 1, 2, 3, 4].map((line) => {
          const y = 24 + line * 52;
          const value = chart.maximum - (line / 4) * (chart.maximum - chart.minimum);
          return <g key={line}><line x1="68" x2="758" y1={y} y2={y} className="chart-grid" /><text x="58" y={y + 3} textAnchor="end" className="chart-label">{value.toExponential(1)}</text></g>;
        })}
        {chart.paths.map(({ name, path }) => <path key={name} d={path} fill="none" stroke={colors[name] ?? "var(--color-ink)"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />)}
        <text x="68" y="252" className="chart-label">{chart.xMinimum.toFixed(2)}</text>
        <text x="758" y="252" textAnchor="end" className="chart-label">{chart.xMaximum.toFixed(2)}</text>
        <text x="413" y="276" textAnchor="middle" className="chart-axis-label">{t("data.preview.xAxis")} · {t("data.preview.xUnit")}</text>
        <text x="14" y="128" textAnchor="middle" className="chart-axis-label" transform="rotate(-90 14 128)">{t("data.preview.yAxis")}</text>
      </svg>
      <figcaption className="chart-legend">
        {chart.paths.map(({ name }) => <span key={name}><i style={{ background: colors[name] ?? "var(--color-ink)" }} />{name}</span>)}
      </figcaption>
      <p className="visually-hidden">{summary}</p>
    </figure>
  );
}
