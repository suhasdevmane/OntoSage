import React from 'react';
import { useTimeSeries, useMappings } from '../../hooks';

interface Props { deviceName?: string; }

// Simple sparkline polyline from series [{ts, ...}]
function Sparkline({ series, primary }: { series: Array<Record<string, any>>; primary?: string }) {
  if (!series?.length || !primary) return <div style={{opacity:.5}}>No data</div>;
  const points = series.map((d,i)=>({ x:i, y: d[primary] })).filter(p=> typeof p.y === 'number');
  if(!points.length) return <div style={{opacity:.5}}>No numeric data</div>;
  const ys = points.map(p=>p.y);
  const min = Math.min(...ys); const max = Math.max(...ys);
  const range = max - min || 1;
  const norm = points.map(p=>({ x:p.x, y: 1 - (p.y - min)/range }));
  const w = 140; const h = 40;
  const step = w / Math.max(1, norm.length - 1);
  const path = norm.map((p,i)=>`${i===0?'M':'L'}${(i*step).toFixed(1)},${(p.y*h).toFixed(1)}`).join(' ');
  return (
    <svg width={w} height={h} style={{display:'block'}}>
      <path d={path} fill="none" stroke="#00ffaa" strokeWidth={2} />
    </svg>
  );
}

export const DataPanel: React.FC<Props> = ({ deviceName }: Props) => {
  const mappings = useMappings() as Array<any> | undefined;
  const mapping = mappings?.find((m: any) => m.device_name === deviceName);
  const ts = useTimeSeries(deviceName || undefined, 3600_000, 20000);
  const primary = mapping?.primary_value_column || mapping?.value_columns?.[0];

  return (
    <div style={{display:'grid', gap:'6px'}}>
      {!mapping && <div style={{fontSize:12,opacity:.75}}>No mapping. (UI to create mapping not implemented yet)</div>}
      {mapping && (
        <>
          <div style={{fontSize:12,opacity:.8}}>
            <strong>Table:</strong> {mapping.table_name} · <strong>Columns:</strong> {mapping.value_columns.join(', ')}
          </div>
          <Sparkline series={ts?.series||[]} primary={primary} />
          {ts?.series?.length && (
            <div style={{display:'grid', gap:4, fontSize:12}}>
              <div style={{opacity:.7}}>Latest:</div>
              {(() => {
                const last = ts.series[ts.series.length-1];
                if(!last) return null;
                return mapping.value_columns.map(col => <div key={col}>{col}: {last[col] === undefined? '—' : last[col]}</div>);
              })()}
            </div>
          )}
        </>
      )}
    </div>
  );
};
