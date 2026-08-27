interface HeatmapProps {
  values?: number[][];
  label?: string;
  emptyLabel: string;
  scaleLabel: string;
  unit: string;
}

function color(value: number, minimum: number, maximum: number): string {
  const ratio = maximum === minimum ? 0.5 : Math.max(0, Math.min(1, (value - minimum) / (maximum - minimum)));
  const hue = 221 - ratio * 34;
  const saturation = 58 + ratio * 24;
  const lightness = 13 + ratio * 60;
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

export function Heatmap({ values, label = "CCD quicklook image", emptyLabel, scaleLabel, unit }: HeatmapProps) {
  if (!values?.length || !values[0]?.length) {
    return <div className="heatmap-empty">{emptyLabel}</div>;
  }
  const flat = values.flat().filter(Number.isFinite);
  const minimum = Math.min(...flat);
  const maximum = Math.max(...flat);
  return (
    <div className="heatmap-figure">
      <div className="heatmap" role="img" aria-label={`${label}; minimum ${minimum.toFixed(1)} ${unit}, maximum ${maximum.toFixed(1)} ${unit}`} style={{ gridTemplateColumns: `repeat(${values[0].length}, 1fr)` }}>
        {values.flatMap((row, y) => row.map((value, x) => <span key={`${y}-${x}`} style={{ background: color(value, minimum, maximum) }} />))}
      </div>
      <div className="heatmap-scale"><span>{minimum.toFixed(0)}</span><i /><span>{maximum.toFixed(0)} {unit}</span><b>{scaleLabel}</b></div>
    </div>
  );
}
