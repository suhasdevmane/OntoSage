import React, { useState, useEffect, useCallback } from 'react';

export default function AuditTab({ api, headers }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/audit`, { headers });
      const d = await r.json();
      setEntries(d.data?.entries || []);
    } finally { setLoading(false); }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="d-flex justify-content-between mb-3">
        <h5>Admin Action Audit Log</h5>
        <button className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>Refresh</button>
      </div>
      <p className="small text-muted">All mutating admin-console actions (100 most recent).</p>
      <div style={{maxHeight:500,overflowY:'auto'}}>
        <table className="table table-sm table-bordered" style={{fontSize:12}}>
          <thead className="table-light sticky-top">
            <tr><th>When</th><th>User</th><th>Method</th><th>Path</th><th>Status</th></tr>
          </thead>
          <tbody>
            {entries.length === 0 && <tr><td colSpan={5} className="text-center text-muted">No actions logged yet</td></tr>}
            {entries.map((e,i) => (
              <tr key={i}>
                <td style={{whiteSpace:'nowrap'}}>{e.created_at?.substring(0,19)}</td>
                <td>{e.username||'-'}</td>
                <td><span className={`badge bg-${e.method==='DELETE'?'danger':e.method==='POST'?'primary':'secondary'}`}>{e.method}</span></td>
                <td style={{wordBreak:'break-all',fontFamily:'monospace'}}>{e.path}</td>
                <td><span className={`badge bg-${e.status_code<300?'success':'warning'}`}>{e.status_code}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
