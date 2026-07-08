import React, { useState, useEffect, useCallback } from 'react';

export default function DataSourcesTab({ api, headers }) {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/datasources`, { headers });
      const d = await r.json();
      setSources(d.data?.sources || []);
    } finally { setLoading(false); }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (id, enable) => {
    setMsg('');
    const action = enable ? 'enable' : 'disable';
    const r = await fetch(`${api}/api/v1/datasources/${id}/${action}`, { method:'POST', headers });
    const d = await r.json();
    setMsg(d.success ? `${enable?'Enabled':'Disabled'} '${id}'` : d.error);
    load();
  };

  const regenerate = async (id) => {
    setMsg(`Regenerating ${id}...`);
    const r = await fetch(`${api}/api/v1/datasources/${id}/regenerate`, { method:'POST', headers });
    const d = await r.json();
    setMsg(d.success ? `Regenerated ${id}` : d.error);
  };

  const resetDemo = async () => {
    if (!window.confirm('Disable all enabled sources? (demo reset)')) return;
    await fetch(`${api}/api/v1/datasources/reset-demo`, { method:'POST', headers });
    setMsg('Demo reset: all sources disabled');
    load();
  };

  return (
    <div>
      {msg && <div className="alert alert-info py-1 mb-3">{msg}</div>}
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h5>Synthetic Data Sources</h5>
        <div className="d-flex gap-2">
          <button className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>Refresh</button>
          <button className="btn btn-sm btn-outline-danger" onClick={resetDemo}>Reset Demo</button>
        </div>
      </div>
      <p className="small text-muted">
        Enabling a source loads its Brick triples into a named graph, making its sensors discoverable via SPARQL.
        Disabling clears that graph.
      </p>
      {sources.length === 0 && <div className="text-muted">No toggleable data sources configured.</div>}
      <div className="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">
        {sources.map(s => (
          <div className="col" key={s.id}>
            <div className={`card h-100 border-${s.enabled?'success':'secondary'}`}>
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-start mb-1">
                  <strong>{s.id}</strong>
                  <span className={`badge bg-${s.enabled?'success':'secondary'}`}>{s.enabled?'Enabled':'Off'}</span>
                </div>
                <div style={{fontSize:12}} className="text-muted mb-2">
                  {s.sensor_count != null && <span>Sensors: {s.sensor_count}</span>}
                  {s.row_count != null && <span> | Rows: {s.row_count}</span>}
                </div>
                <div className="d-flex gap-1">
                  <button className={`btn btn-xs py-0 px-2 btn-${s.enabled?'outline-secondary':'success'}`}
                    style={{fontSize:11}} onClick={() => toggle(s.id, !s.enabled)}>
                    {s.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button className="btn btn-xs py-0 px-2 btn-outline-primary" style={{fontSize:11}}
                    onClick={() => regenerate(s.id)}>Regenerate</button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
