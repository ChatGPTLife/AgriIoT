import { useMemo, useState, type FC, type MouseEvent } from "react";
import type { SensorReading } from "../types";

interface Props {
  readings: SensorReading[];
  threshold: number;
  target?: number;
  height?: number;
}

const W = 1000; // viewBox width; the SVG scales to its container
const PAD = { top: 16, right: 12, bottom: 28, left: 36 };

// Catmull-Rom → cubic Bézier for a smooth line through every point.
function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`;
  }
  return d;
}

export const MoistureChart: FC<Props> = ({ readings, threshold, target, height = 220 }) => {
  const [hover, setHover] = useState<number | null>(null);

  const geo = useMemo(() => {
    if (readings.length < 2) return null;
    const times = readings.map((r) => new Date(r.timestamp).getTime());
    const values = readings.map((r) => r.soil_moisture);
    const t0 = times[0];
    const t1 = times[times.length - 1];
    const lo = Math.floor(Math.min(...values, threshold) / 5) * 5 - 5;
    const hi = Math.ceil(Math.max(...values, target ?? threshold) / 5) * 5 + 5;
    const x = (t: number) => PAD.left + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (height - PAD.top - PAD.bottom);
    const pts = times.map((t, i) => [x(t), y(values[i])] as [number, number]);
    const line = smoothPath(pts);
    const area = `${line} L${pts[pts.length - 1][0]},${height - PAD.bottom} L${pts[0][0]},${height - PAD.bottom} Z`;
    const step = (hi - lo) / 4;
    const grid = [0, 1, 2, 3, 4].map((i) => lo + i * step);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + f * (t1 - t0));
    return { pts, line, area, grid, ticks, x, y };
  }, [readings, threshold, target, height]);

  if (!geo) {
    return <div className="chart-empty">Not enough readings yet to draw a trend.</div>;
  }

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    geo.pts.forEach((p, i) => {
      if (Math.abs(p[0] - vx) < Math.abs(geo.pts[best][0] - vx)) best = i;
    });
    setHover(best);
  };

  const h = hover !== null ? readings[hover] : null;
  const hp = hover !== null ? geo.pts[hover] : null;

  return (
    <div className="chart" style={{ height }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="Soil moisture trend"
      >
        <defs>
          <linearGradient id="moisture-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {geo.grid.map((v) => (
          <line key={v} x1={PAD.left} x2={W - PAD.right} y1={geo.y(v)} y2={geo.y(v)} className="chart__grid" />
        ))}
        <line
          x1={PAD.left} x2={W - PAD.right} y1={geo.y(threshold)} y2={geo.y(threshold)}
          className="chart__threshold"
        />
        <path d={geo.area} fill="url(#moisture-fill)" />
        <path d={geo.line} className="chart__line" />
        {hp && (
          <>
            <line x1={hp[0]} x2={hp[0]} y1={PAD.top} y2={height - PAD.bottom} className="chart__cursor" />
            <circle cx={hp[0]} cy={hp[1]} r={4.5} className="chart__dot" />
          </>
        )}
      </svg>
      {/* HTML labels so text isn't stretched by preserveAspectRatio="none" */}
      {geo.grid.map((v) => (
        <span key={v} className="chart__ylabel" style={{ top: geo.y(v) }}>{Math.round(v)}%</span>
      ))}
      <span className="chart__threshold-label" style={{ top: geo.y(threshold) }}>threshold {threshold}%</span>
      {geo.ticks.map((t, i) => (
        <span
          key={t}
          className="chart__xlabel"
          style={{ left: `${(geo.x(t) / W) * 100}%`, transform: i === 0 ? "none" : i === 4 ? "translateX(-100%)" : "translateX(-50%)" }}
        >
          {new Date(t).toLocaleString("en-IN", { weekday: "short", hour: "numeric" })}
        </span>
      ))}
      {h && hp && (
        <div className="chart__tooltip" style={{ left: `${(hp[0] / W) * 100}%`, top: hp[1] }}>
          <strong>{h.soil_moisture.toFixed(1)}%</strong>
          <span>{new Date(h.timestamp).toLocaleString("en-IN", { weekday: "short", hour: "numeric", minute: "2-digit" })}</span>
        </div>
      )}
    </div>
  );
};
