import React, { useState, useEffect, useCallback } from 'react';

// V5-T43 — access-policy editor. Policies are ontosage:AccessPolicy triples that
// the PDP enforces at every fetch chokepoint, so this tab is the governance
// surface: edit a k-anonymity floor here and the next question obeys it.
//
// Two refusals are deliberate and enforced server-side; the UI mirrors them so an
// operator sees WHY before submitting rather than after:
//   * a change that weakens a guarantee needs an explicit acknowledgement
//   * the individual-privacy rules are read-only ("never track individuals")

const BLANK = {
  id: '',
  role: 'occupant',
  scope_spaces: 'any',
  min_sensors: 3,
  min_spaces: 2,
  tiers: '0:900,60:60',
  rate_max: 0,
  rate_window_min: 0,
  comment: '',
};

const localOk = (s) => /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(s || '');
const tiersOk = (s) => !s || /^\s*\d+(\.\d+)?\s*:\s*\d+(\.\d+)?\s*(,\s*\d+(\.\d+)?\s*:\s*\d+(\.\d+)?\s*)*$/.test(s);

// Mirrors policy_admin.diff_weakening so the warning appears BEFORE the round trip.
function weakenings(oldP, form) {
  if (!oldP) return [];
  const out = [];
  const n = (v) => (v === '' || v === null || v === undefined ? 0 : Number(v));
  if (n(form.min_sensors) < n(oldP.min_sensors)) {
    out.push(`sensor k-anonymity floor ${oldP.min_sensors} → ${form.min_sensors}`);
  }
  if (n(form.min_spaces) < n(oldP.min_spaces)) {
    out.push(`space k-anonymity floor ${oldP.min_spaces} → ${form.min_spaces}`);
  }
  if (n(oldP.rate_max) && (!n(form.rate_max) || n(form.rate_max) > n(oldP.rate_max))) {
    out.push(`rate limit ${oldP.rate_max} → ${n(form.rate_max) || 'unlimited'}`);
  }
  const map = (s) => Object.fromEntries(
    String(s || '').split(',').filter((p) => p.includes(':')).map((p) => p.split(':').map(Number))
  );
  const oldT = map(oldP.tiers); const newT = map(form.tiers);
  Object.entries(oldT).forEach(([k, v]) => {
    if (newT[k] !== undefined && newT[k] < v) out.push(`resolution at ${k} min ${v}s → ${newT[k]}s (finer data)`);
  });
  return out;
}

export default function PoliciesTab({ api, headers }) {
  const [policies, setPolicies] = useState([]);
  const [roles, setRoles] = useState(['*']);
  const [mode, setMode] = useState('unknown');
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [ack, setAck] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/policies`, { headers });
      const d = await r.json();
      setPolicies(d.data?.policies || []);
      if (d.data?.roles?.length) setRoles(d.data.roles);
      setMode(d.data?.enforcement_mode || 'unknown');
    } catch (e) {
      setPolicies([]);
    } finally {
      setLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const existing = policies.find((p) => p.id === form.id);
  const willWeaken = weakenings(existing, form);
  const canSave = form.id && localOk(form.id) && tiersOk(form.tiers)
    && Number(form.min_sensors) >= 1 && Number(form.min_spaces) >= 1
    && (!willWeaken.length || ack);

  const edit = (p) => {
    setForm({
      id: p.id, role: p.role, scope_spaces: p.scope_spaces, min_sensors: p.min_sensors,
      min_spaces: p.min_spaces, tiers: p.tiers, rate_max: p.rate_max,
      rate_window_min: p.rate_window_min, comment: p.comment || '',
    });
    setAck(false); setMsg(null);
  };

  const save = async () => {
    setSaving(true); setMsg(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/policies`, {
        method: 'POST', headers,
        body: JSON.stringify({ ...form, acknowledge_weakening: ack }),
      });
      const d = await r.json();
      if (d.success) {
        setMsg({ ok: true, text: `Saved ${form.id}. The PDP was reloaded and the response cache flushed — the next question obeys it.` });
        setForm(BLANK); setAck(false); load();
      } else {
        setMsg({ ok: false, text: d.error || 'save failed' });
      }
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete policy ${p.id}? Role '${p.role}' then falls back to the next matching policy.`)) return;
    const r = await fetch(`${api}/api/v1/admin/policies/${encodeURIComponent(p.id)}`, { method: 'DELETE', headers });
    const d = await r.json();
    setMsg({ ok: !!d.success, text: d.success ? `Deleted ${p.id}` : (d.error || 'delete failed') });
    load();
  };

  return (
    <div>
      <div className="d-flex align-items-center mb-2">
        <h5 className="me-3 mb-0">Access policies</h5>
        <span className={`badge ${mode === 'on' ? 'bg-success' : 'bg-secondary'}`}>
          enforcement: {mode}
        </span>
        <button className="btn btn-sm btn-outline-secondary ms-auto" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      <p className="text-muted small">
        Every policy is a triple in <code>input/&lt;building&gt;_policies.ttl</code>, so an edit here
        lands in the same versioned file a reviewer reads. Saving reloads the decision point and
        flushes cached answers, so the change binds on the next question.
        {mode !== 'on' && (
          <span className="text-warning"> Enforcement is <b>{mode}</b> — policies are evaluated but not applied.</span>
        )}
      </p>

      {msg && <div className={`alert ${msg.ok ? 'alert-success' : 'alert-danger'} py-2`}>{msg.text}</div>}

      <div className="table-responsive mb-4">
        <table className="table table-sm table-hover align-middle">
          <thead>
            <tr>
              <th>Policy</th><th>Role</th><th>Scope</th><th>k sensors</th><th>k spaces</th>
              <th>Tiers</th><th>Rate</th><th></th>
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id} className={p.editable ? '' : 'table-light'}>
                <td><code>{p.id}</code>{!p.editable && <span className="badge bg-dark ms-2">privacy rule</span>}</td>
                <td>{p.role}</td>
                <td>{p.inference_class ? <em>{p.inference_class}</em> : p.scope_spaces}</td>
                <td>{p.inference_class ? '—' : p.min_sensors}</td>
                <td>{p.inference_class ? '—' : p.min_spaces}</td>
                <td><small>{p.tiers || '—'}</small></td>
                <td><small>{p.rate_max ? `${p.rate_max}/${p.rate_window_min}m` : 'unlimited'}</small></td>
                <td className="text-end">
                  {p.editable ? (
                    <>
                      <button className="btn btn-sm btn-outline-primary me-1" onClick={() => edit(p)}>Edit</button>
                      <button className="btn btn-sm btn-outline-danger" onClick={() => remove(p)}>Delete</button>
                    </>
                  ) : (
                    <span className="text-muted small" title="The system explains the building; it never tracks individuals. Edit the TTL directly to change this.">
                      read-only
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!policies.length && !loading && (
              <tr><td colSpan="8" className="text-muted">No policies loaded — the PDP is idle.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <h6>{existing ? `Edit ${form.id}` : 'New policy'}</h6>
      <div className="row g-2">
        <div className="col-md-3">
          <label className="form-label small">Policy id</label>
          <input className={`form-control form-control-sm ${form.id && !localOk(form.id) ? 'is-invalid' : ''}`}
                 value={form.id} onChange={set('id')} placeholder="policy_occupant_full" />
        </div>
        <div className="col-md-2">
          <label className="form-label small">Role</label>
          <select className="form-select form-select-sm" value={form.role} onChange={set('role')}>
            {roles.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="col-md-2">
          <label className="form-label small">Scope</label>
          <input className="form-control form-control-sm" value={form.scope_spaces} onChange={set('scope_spaces')} />
        </div>
        <div className="col-md-2">
          <label className="form-label small">Min sensors (k)</label>
          <input type="number" min="1" className="form-control form-control-sm"
                 value={form.min_sensors} onChange={set('min_sensors')} />
        </div>
        <div className="col-md-2">
          <label className="form-label small">Min spaces (k)</label>
          <input type="number" min="1" className="form-control form-control-sm"
                 value={form.min_spaces} onChange={set('min_spaces')} />
        </div>
        <div className="col-md-3">
          <label className="form-label small">Resolution tiers</label>
          <input className={`form-control form-control-sm ${tiersOk(form.tiers) ? '' : 'is-invalid'}`}
                 value={form.tiers} onChange={set('tiers')} placeholder="0:900,60:60" />
          <div className="form-text">minutes:seconds pairs — how coarse recent data must be</div>
        </div>
        <div className="col-md-2">
          <label className="form-label small">Max queries</label>
          <input type="number" min="0" className="form-control form-control-sm"
                 value={form.rate_max} onChange={set('rate_max')} />
        </div>
        <div className="col-md-2">
          <label className="form-label small">Per minutes</label>
          <input type="number" min="0" className="form-control form-control-sm"
                 value={form.rate_window_min} onChange={set('rate_window_min')} />
        </div>
        <div className="col-md-5">
          <label className="form-label small">Why this policy exists</label>
          <input className="form-control form-control-sm" value={form.comment} onChange={set('comment')}
                 placeholder="Occupants get coarse aggregates only." />
        </div>
      </div>

      {willWeaken.length > 0 && (
        <div className="alert alert-warning mt-3 py-2">
          <b>This change weakens a privacy guarantee:</b>
          <ul className="mb-2 mt-1">{willWeaken.map((w) => <li key={w}>{w}</li>)}</ul>
          <div className="form-check">
            <input className="form-check-input" type="checkbox" id="ackWeaken"
                   checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <label className="form-check-label" htmlFor="ackWeaken">
              I understand and intend this. The change will be recorded against my account.
            </label>
          </div>
        </div>
      )}

      <div className="mt-3">
        <button className="btn btn-primary btn-sm" disabled={!canSave || saving} onClick={save}>
          {saving ? 'Saving…' : existing ? 'Update policy' : 'Create policy'}
        </button>
        <button className="btn btn-link btn-sm" onClick={() => { setForm(BLANK); setAck(false); setMsg(null); }}>
          Reset
        </button>
      </div>
    </div>
  );
}
