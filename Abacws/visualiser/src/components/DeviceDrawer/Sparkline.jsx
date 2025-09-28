import React from 'react';

export function Sparkline({ points, color = '#0ea5e9' }) {
  if (!points || points.length < 2) return <div className="empty">No history</div>;
  const w = 300; const h = 50; const pad = 2;
  const xs = points.map(p => p.timestamp);
  const ys = points.map(p => p.value).filter(v => typeof v === 'number');
  if(!ys.length) return <div className="empty">No numeric data</div>;
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const scaleX = (x) => pad + ((x - minX) / (maxX - minX || 1)) * (w - pad*2);
  const scaleY = (y) => pad + (1 - ((y - minY) / (maxY - minY || 1))) * (h - pad*2);
  const d = points.map((p,i) => `${i? 'L':'M'}${scaleX(p.timestamp)},${scaleY(p.value)}`).join(' ');
  const fillD = d + ` L ${scaleX(maxX)},${h-pad} L ${scaleX(minX)},${h-pad} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="sparkline-svg" role="img" aria-label="history sparkline">
      <path className="fill" d={fillD} />
      <path className="line" d={d} stroke={color} />
    </svg>
  );
}
