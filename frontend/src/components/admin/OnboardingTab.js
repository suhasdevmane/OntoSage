import React, { useState, useEffect, useCallback } from 'react';

/**
 * Onboard a building end-to-end, from an empty input/, without touching a file
 * on the server (TODO-072).
 *
 * Every step below already had a backend endpoint. Three of them had no control
 * anywhere in the console — identity, documents and floor plans — so the
 * portability claim "a building is onboarded entirely through the Admin Console"
 * was true of the API and false of the product. This screen closes that, and
 * shows readiness per step so an admin can see WHICH step is missing rather than
 * inferring it from a disappointing answer.
 *
 * Readiness comes from the live system, not from what has been uploaded: the
 * ontology step counts spaces in the graph, sensor data compares declared
 * sensors against UUIDs that actually have rows.
 */
export default function OnboardingTab({ api, headers, onNavigate }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [identity, setIdentity] = useState({ building_name: '', ontology_namespace: '', ontology_prefix: '' });
  const [docs, setDocs] = useState([]);
  const [plans, setPlans] = useState([]);

  const jsonHeaders = { ...headers, 'Content-Type': 'application/json' };

  const load = useCallback(async () => {
    try {
      const [s, cfg, d, f] = await Promise.all([
        fetch(`${api}/api/v1/admin/onboarding/status`, { headers }).then(r => r.json()),
        fetch(`${api}/api/v1/admin/building/config`, { headers }).then(r => r.json()),
        fetch(`${api}/api/v1/admin/documents`, { headers }).then(r => r.json()),
        fetch(`${api}/api/v1/admin/floor-plans/files`, { headers }).then(r => r.json()),
      ]);
      setStatus(s.data);
      if (cfg.data) {
        setIdentity({
          building_name: cfg.data.building_name || '',
          ontology_namespace: cfg.data.ontology_namespace || '',
          ontology_prefix: cfg.data.ontology_prefix || '',
        });
      }
      setDocs(d.data?.documents || []);
      // The endpoint returns `floor_plans` (verified against the live API), not `files`.
      setPlans(f.data?.floor_plans || []);
    } catch (e) {
      setMsg({ kind: 'danger', text: `Could not load onboarding status: ${e.message}` });
    }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const saveIdentity = async () => {
    setBusy('identity'); setMsg(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/building/config`, {
        method: 'PUT', headers: jsonHeaders, body: JSON.stringify(identity),
      });
      const d = await r.json();
      setMsg(d.success
        ? { kind: 'success', text: 'Identity saved. Restart the orchestrator to apply it — the namespace is read at boot.' }
        : { kind: 'danger', text: d.error || 'Could not save identity' });
      if (d.success) load();
    } finally { setBusy(''); }
  };

  const upload = async (kind, file) => {
    if (!file) return;
    setBusy(kind); setMsg(null);
    const path = kind === 'document' ? 'documents/upload' : 'floor-plans/upload';
    const body = new FormData();
    body.append('file', file);
    try {
      // Deliberately NOT setting Content-Type: the browser must add the
      // multipart boundary itself, and an explicit header suppresses it.
      const { 'Content-Type': _drop, ...authOnly } = headers;
      const r = await fetch(`${api}/api/v1/admin/${path}`, { method: 'POST', headers: authOnly, body });
      const d = await r.json();
      setMsg(d.success
        ? { kind: 'success', text: `${file.name} uploaded${kind === 'document' ? ' and indexed' : ' and ingested'}.` }
        : { kind: 'danger', text: d.error || 'Upload failed' });
      load();
    } catch (e) {
      setMsg({ kind: 'danger', text: e.message });
    } finally { setBusy(''); }
  };

  const removeDoc = async (name) => {
    setBusy('document');
    try {
      await fetch(`${api}/api/v1/admin/documents/${encodeURIComponent(name)}`, { method: 'DELETE', headers });
      load();
    } finally { setBusy(''); }
  };

  const stepOf = (key) => (status?.steps || []).find(s => s.key === key) || {};

  const Badge = ({ step }) => {
    if (step.done) return <span className="badge bg-success">ready</span>;
    if (step.blocking) return <span className="badge bg-danger">required</span>;
    return <span className="badge bg-secondary">optional</span>;
  };

  const Step = ({ n, keyName, title, children }) => {
    const s = stepOf(keyName);
    return (
      <div className="card mb-3">
        <div className="card-header d-flex justify-content-between align-items-center">
          <span><strong>{n}. {title}</strong></span>
          <Badge step={s} />
        </div>
        <div className="card-body">
          <p className="small text-muted mb-2">{s.detail || '—'}</p>
          {!s.done && s.hint && <p className="small text-warning mb-2">{s.hint}</p>}
          {children}
        </div>
      </div>
    );
  };

  return (
    <div>
      <h5>Onboard a building</h5>
      <p className="small text-muted">
        Every step here writes through the API — no file needs to be placed on the server by hand.
        Readiness is read from the live system, so a step turns green because the data is actually
        there, not because something was uploaded.
      </p>

      {status && (
        <div className={`alert alert-${status.can_answer ? 'success' : 'warning'} py-2`}>
          <strong>{status.building_id || '(no building id)'}</strong>{' — '}
          {status.can_answer
            ? 'can answer questions'
            : 'cannot answer yet: identity and ontology are both required'}
          {' · '}{status.steps_done}/{status.steps_total} steps complete
        </div>
      )}

      {msg && <div className={`alert alert-${msg.kind} py-2`}>{msg.text}</div>}

      <Step n={1} keyName="identity" title="Building identity">
        <div className="row g-2">
          <div className="col-md-4">
            <label className="form-label small">Building name</label>
            <input className="form-control form-control-sm" value={identity.building_name}
              onChange={e => setIdentity({ ...identity, building_name: e.target.value })} />
          </div>
          <div className="col-md-5">
            <label className="form-label small">Ontology namespace</label>
            <input className="form-control form-control-sm" value={identity.ontology_namespace}
              placeholder="http://your-org.org/ontologies/yourbuilding#"
              onChange={e => setIdentity({ ...identity, ontology_namespace: e.target.value })} />
          </div>
          <div className="col-md-3">
            <label className="form-label small">Prefix</label>
            <input className="form-control form-control-sm" value={identity.ontology_prefix}
              onChange={e => setIdentity({ ...identity, ontology_prefix: e.target.value })} />
          </div>
        </div>
        <button className="btn btn-primary btn-sm mt-2" onClick={saveIdentity} disabled={busy === 'identity'}>
          {busy === 'identity' ? 'Saving…' : 'Save identity'}
        </button>
        <div className="form-text">
          The namespace must match the <code>@prefix</code> in the TTL you upload next — the validator
          hard-fails on a mismatch rather than loading a graph nothing can query.
        </div>
      </Step>

      <Step n={2} keyName="ontology" title="Ontology (Brick / BACnet TTL)">
        <button className="btn btn-outline-primary btn-sm" onClick={() => onNavigate && onNavigate('ontology')}>
          Go to Ontology tab →
        </button>
        <div className="form-text">Validate before uploading; each file becomes its own named graph.</div>
      </Step>

      <Step n={3} keyName="timeseries" title="Sensor data">
        <button className="btn btn-outline-primary btn-sm" onClick={() => onNavigate && onNavigate('databases')}>
          Go to Databases tab →
        </button>
        <div className="form-text">
          A question is answerable only when the sensor is a triple <em>and</em> its readings are rows,
          linked by <code>ref:hasTimeseriesId</code> + <code>ref:storedAt</code>. Both halves are counted above.
        </div>
      </Step>

      <Step n={4} keyName="documents" title="Documents (policies, manuals)">
        <input type="file" className="form-control form-control-sm" accept=".md,.txt,.pdf"
          disabled={busy === 'document'}
          onChange={e => { upload('document', e.target.files[0]); e.target.value = ''; }} />
        {docs.length > 0 && (
          <ul className="list-group list-group-flush mt-2">
            {docs.map(d => (
              <li key={d.filename} className="list-group-item d-flex justify-content-between align-items-center py-1">
                <span className="small"><code>{d.filename}</code> <span className="text-muted">({Math.round(d.bytes / 1024)} KB)</span></span>
                <button className="btn btn-outline-danger btn-sm py-0" onClick={() => removeDoc(d.filename)}>remove</button>
              </li>
            ))}
          </ul>
        )}
        <div className="form-text">Indexed on upload; answers cite the document they came from.</div>
      </Step>

      <Step n={5} keyName="floor_plans" title="Floor plans">
        <input type="file" className="form-control form-control-sm" accept=".pdf,.dwg,.dxf"
          disabled={busy === 'floor_plan'}
          onChange={e => { upload('floor_plan', e.target.files[0]); e.target.value = ''; }} />
        {plans.length > 0 && (
          <ul className="list-group list-group-flush mt-2">
            {plans.map(p => (
              <li key={p.filename || p} className="list-group-item py-1 small">
                <code>{p.filename || p}</code>
              </li>
            ))}
          </ul>
        )}
        <div className="form-text">
          Name files <code>&lt;building&gt; floor &lt;N&gt;.pdf</code>. A DWG/DXF alongside the PDF adds
          real geometry — areas and adjacency — which the PDF alone cannot provide.
        </div>
      </Step>

      {(status?.capabilities || []).length > 0 && (
        <>
          <h5 className="mt-4">What this building can answer</h5>
          <p className="small text-muted">
            The steps above are what you configured; these are what it buys. A locked capability
            names the specific artefact it still needs, not a vague &quot;not configured&quot;.
          </p>
          <div className="table-responsive">
            <table className="table table-sm table-bordered">
              <thead className="table-light">
                <tr><th>Capability</th><th>State</th><th>Why</th><th>Still needs</th><th>Example question</th></tr>
              </thead>
              <tbody>
                {status.capabilities.map(c => (
                  <tr key={c.name}>
                    <td><code>{c.name}</code></td>
                    <td>
                      <span className={`badge bg-${c.state === 'unlocked' ? 'success' : c.state === 'partial' ? 'warning text-dark' : 'secondary'}`}>
                        {c.state}
                      </span>
                    </td>
                    <td className="small">{c.why}</td>
                    <td className="small">{(c.missing || []).join('; ') || '—'}</td>
                    <td className="small text-muted"><em>{c.example_question}</em></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <button className="btn btn-outline-secondary btn-sm" onClick={load}>Refresh readiness</button>
    </div>
  );
}
