import React, { useState, useEffect, useCallback } from 'react';

/**
 * What the active building currently has indexed, and how to rebuild it.
 *
 * This screen used to report the capability.yaml Qdrant KB. That KB is gone —
 * structured capability facts are ontosage:Amenity / ontosage:KnowledgeTopic
 * TRIPLES now, published by uploading TTL on the Capabilities screen, so there
 * is no vector index behind them to rebuild. What is left that genuinely gets
 * indexed is the document KB (uploaded manuals and policies), which is what an
 * admin needs to see before asking why a question went unanswered.
 */
export default function IndexStatusTab({ api, headers }) {
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [targets, setTargets] = useState({ documents: true, floor_plans: false });
  const [activeJob, setActiveJob] = useState(null);
  const [polling, setPolling] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const r = await fetch(`${api}/api/v1/admin/index-status`, { headers });
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

  const docs = status?.documents || {};
  const caps = status?.capabilities || {};

  return (
    <div>
      <h5>Capabilities (ontology triples)</h5>
      <p className="small text-muted">
        Answered straight from the graph — no vector index, nothing to rebuild.
        Publish or edit these on the <strong>Capabilities</strong> tab.
      </p>
      <div className="mb-4">
        {caps.available ? (
          <>
            <span className="badge bg-success me-2">Amenities: {caps.amenities}</span>
            <span className="badge bg-success me-2">Knowledge topics: {caps.knowledge_topics}</span>
            {(caps.amenities === 0 && caps.knowledge_topics === 0) && (
              <span className="small text-danger">
                None loaded — a capability question will honestly say it has no information.
                Upload <code>&lt;building&gt;_capabilities.ttl</code> on the Capabilities tab.
              </span>
            )}
          </>
        ) : (
          <span className="badge bg-warning text-dark">
            Graph unreachable — count unknown{caps.reason ? `: ${caps.reason}` : ''}
          </span>
        )}
      </div>

      <h5>Document KB Index Status</h5>
      <div className="table-responsive mb-4">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Building</th><th>Status</th><th>Documents</th><th>Chunks</th><th>Reason</th></tr>
          </thead>
          <tbody>
            {Object.entries(docs).length === 0 && (
              <tr><td colSpan={5} className="text-center text-muted">
                No documents indexed — drop files into the building&apos;s <code>documents/</code> folder, then re-index.
              </td></tr>
            )}
            {Object.entries(docs).map(([bid, b]) => (
              <tr key={bid}>
                <td><code>{bid}</code></td>
                <td>
                  <span className={`badge bg-${b.status==='indexed'?'success':b.status==='degraded'?'warning':'secondary'}`}>
                    {b.status}
                  </span>
                </td>
                <td>{b.documents}</td>
                <td>{b.chunks}</td>
                <td style={{fontSize:11}}>{b.reason||'-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mb-4 small text-muted">
        Embedding: <code>{status?.embedding_provider || 'unknown'}</code>
        {status?.embedding_dimension ? ` · ${status.embedding_dimension}-d` : ''}
        {' — '}a collection written under a different model returns nothing rather than failing,
        so re-index after changing provider.
      </div>

      <div className="card mb-4" style={{maxWidth:520}}>
        <div className="card-header"><strong>Trigger Re-index</strong></div>
        <div className="card-body">
          <p className="small text-muted">Run after uploading new documents to make them searchable.</p>
          <div className="mb-2">
            {['documents', 'floor_plans'].map(t => (
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
