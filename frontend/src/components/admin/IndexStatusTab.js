import React, { useState, useEffect, useCallback } from 'react';

export default function IndexStatusTab({ api, headers }) {
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [targets, setTargets] = useState({ capability: true, documents: false });
  const [activeJob, setActiveJob] = useState(null);
  const [polling, setPolling] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch(`${api}/api/v1/admin/capability-indexer/status`, { headers });
      setStatus((await r.json()).data);
    } catch {}
  }, [api, headers]);

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetch(`${api}/api/v1/admin/reindex`, { headers });
      setJobs((await r.json()).data?.jobs || []);
    } catch {}
  }, [api, headers]);

  useEffect(() => { loadStatus(); loadJobs(); }, [loadStatus, loadJobs]);

  const triggerReindex = async () => {
    const chosen = Object.entries(targets).filter(([,v])=>v).map(([k])=>k);
    if (chosen.length === 0) return;
    const r = await fetch(`${api}/api/v1/admin/reindex`, {
      method: 'POST', headers, body: JSON.stringify({ targets: chosen })
    });
    const d = await r.json();
    if (d.success) {
      setActiveJob(d.data.job_id);
      setPolling(true);
    }
  };

  useEffect(() => {
    if (!polling || !activeJob) return;
    const interval = setInterval(async () => {
      const r = await fetch(`${api}/api/v1/admin/reindex/${activeJob}`, { headers });
      const d = await r.json();
      const job = d.data;
      if (job?.status === 'done' || job?.status === 'error') {
        setPolling(false);
        loadStatus();
        loadJobs();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, activeJob, api, headers, loadStatus, loadJobs]);

  const bldgStatus = status?.buildings || {};

  return (
    <div>
      <h5>Capability KB Index Status</h5>
      <div className="table-responsive mb-4">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Building</th><th>Status</th><th>Entries (YAML)</th><th>Points (Qdrant)</th><th>Duration</th><th>Reason</th></tr>
          </thead>
          <tbody>
            {Object.entries(bldgStatus).length === 0 && (
              <tr><td colSpan={6} className="text-center text-muted">Not loaded (GET /health for diagnostics)</td></tr>
            )}
            {Object.entries(bldgStatus).map(([bid, b]) => (
              <tr key={bid}>
                <td><code>{bid}</code></td>
                <td>
                  <span className={`badge bg-${b.status==='indexed'?'success':b.status==='degraded'?'warning':'secondary'}`}>
                    {b.status}
                  </span>
                </td>
                <td>{b.entries}</td>
                <td>{b.points}</td>
                <td>{b.duration_ms}ms</td>
                <td style={{fontSize:11}}>{b.reason||'-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card mb-4" style={{maxWidth:520}}>
        <div className="card-header"><strong>Trigger Re-index</strong></div>
        <div className="card-body">
          <p className="small text-muted">Run after uploading new TTL or registering sensors to make new knowledge discoverable.</p>
          <div className="mb-2">
            {['capability', 'documents', 'floor_plans'].map(t => (
              <div className="form-check form-check-inline" key={t}>
                <input className="form-check-input" type="checkbox" id={`tgt-${t}`}
                  checked={!!targets[t]}
                  onChange={e => setTargets(prev => ({ ...prev, [t]: e.target.checked }))} />
                <label className="form-check-label" htmlFor={`tgt-${t}`}>{t}</label>
              </div>
            ))}
          </div>
          <button className="btn btn-primary btn-sm" onClick={triggerReindex}
            disabled={polling || !Object.values(targets).some(Boolean)}>
            {polling ? `Indexing (job: ${activeJob})...` : 'Start Re-index'}
          </button>
        </div>
      </div>

      <h5>Recent Re-index Jobs</h5>
      <div className="table-responsive">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Job ID</th><th>Targets</th><th>Status</th><th>Elapsed</th><th>Results</th></tr>
          </thead>
          <tbody>
            {jobs.length === 0 && <tr><td colSpan={5} className="text-center text-muted">No jobs this session</td></tr>}
            {jobs.map(j => (
              <tr key={j.id}>
                <td><code>{j.id}</code></td>
                <td>{j.targets?.join(', ')}</td>
                <td><span className={`badge bg-${j.status==='done'?'success':j.status==='error'?'danger':'info'}`}>{j.status}</span></td>
                <td>{j.elapsed_s}s</td>
                <td style={{fontSize:11}}>{JSON.stringify(j.results)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
