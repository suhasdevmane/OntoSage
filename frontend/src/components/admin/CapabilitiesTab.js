import React, { useState, useEffect, useCallback } from 'react';

// Guided capability authoring (TODO-014). An admin adds a building amenity
// ("there is a prayer room on floor 1") as live ontosage:Amenity triples via a
// form — no hand-written Turtle. The CapabilityGraphResolver answers it immediately.

const BLANK = {
  id: '',
  type: 'Facility',
  label: '',
  location: '',
  floor: '',
  category: '',
  lay_terms: '',
  note: '',
};

// Short local name (letters/digits/_.-), mirrors the backend regex.
const localOk = (s) => /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(s || '');

function localName(uri) {
  const s = String(uri || '');
  const i = Math.max(s.lastIndexOf('#'), s.lastIndexOf('/'));
  return i >= 0 ? s.slice(i + 1) : s;
}

export default function CapabilitiesTab({ api, headers }) {
  const [amenities, setAmenities] = useState([]);
  const [types, setTypes] = useState(['Facility']);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text}

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/capabilities`, { headers });
      const d = await r.json();
      setAmenities(d.data?.amenities || []);
      if (d.data?.types?.length) setTypes(d.data.types);
    } catch (e) {
      setAmenities([]);
    } finally {
      setLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const canSave = form.id && form.label && form.type && localOk(form.id);

  const handleCreate = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/capabilities`, {
        method: 'POST', headers, body: JSON.stringify(form),
      });
      const d = await r.json();
      if (d.success) {
        setMsg({ ok: true, text: `Added capability: ${localName(d.data?.subject)}` });
        setForm(BLANK);
        load();
      } else {
        setMsg({ ok: false, text: d.error || 'Failed to add capability' });
      }
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (uri) => {
    const name = localName(uri);
    if (!window.confirm(`Delete capability "${name}"?\n\nIt is removed from the building's capability TTL file (a backup is saved to input/.trash/ first) and its graph re-synced, so the deletion persists across restarts.`)) return;
    setMsg(null);
    const r = await fetch(`${api}/api/v1/admin/capabilities/${encodeURIComponent(name)}`, {
      method: 'DELETE', headers,
    });
    const d = await r.json();
    setMsg(d.success ? { ok: true, text: `Deleted: ${name}` } : { ok: false, text: d.error || 'Delete failed' });
    load();
  };

  return (
    <div className="row g-4">
      {/* ── Guided add form ── */}
      <div className="col-12 col-xl-5">
        <div className="card h-100">
          <div className="card-header"><strong>Add a Capability</strong></div>
          <div className="card-body">
            <p className="text-muted small mb-3">
              Describe a building amenity in plain terms. It is stored as live ontology
              triples (<code>ontosage:Amenity</code>) and becomes answerable immediately —
              no Turtle, no code change.
            </p>

            <div className="mb-2">
              <label className="form-label small">Type</label>
              <select className="form-select form-select-sm" value={form.type} onChange={set('type')}>
                {types.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            <div className="mb-2">
              <label className="form-label small">ID <span className="text-danger">*</span></label>
              <input className="form-control form-control-sm font-monospace" value={form.id}
                onChange={set('id')} placeholder="PrayerRoom_104" />
              {form.id && !localOk(form.id) && (
                <small className="text-danger">Use letters, digits, _ . - (no spaces), starting with a letter.</small>
              )}
            </div>

            <div className="mb-2">
              <label className="form-label small">Label <span className="text-danger">*</span></label>
              <input className="form-control form-control-sm" value={form.label}
                onChange={set('label')} placeholder="Prayer & Reflection Room" />
            </div>

            <div className="row">
              <div className="col-8 mb-2">
                <label className="form-label small">Location</label>
                <input className="form-control form-control-sm" value={form.location}
                  onChange={set('location')} placeholder="Room 1.04, first floor" />
              </div>
              <div className="col-4 mb-2">
                <label className="form-label small">Floor</label>
                <input className="form-control form-control-sm" value={form.floor}
                  onChange={set('floor')} placeholder="1" />
              </div>
            </div>

            <div className="mb-2">
              <label className="form-label small">Category</label>
              <input className="form-control form-control-sm" value={form.category}
                onChange={set('category')} placeholder="wellbeing" />
            </div>

            <div className="mb-2">
              <label className="form-label small">Lay terms (comma-separated)</label>
              <input className="form-control form-control-sm" value={form.lay_terms}
                onChange={set('lay_terms')} placeholder="pray, prayer, quiet room, reflection" />
              <small className="text-muted">How users might refer to it in plain English.</small>
            </div>

            <div className="mb-3">
              <label className="form-label small">Note</label>
              <textarea className="form-control form-control-sm" rows={2} value={form.note}
                onChange={set('note')} placeholder="Open 24/7 to staff and students." />
            </div>

            {msg && (
              <div className={`alert py-1 alert-${msg.ok ? 'success' : 'danger'} mb-2`} style={{ fontSize: 12 }}>
                {msg.text}
              </div>
            )}

            <div className="d-flex gap-2">
              <button className="btn btn-primary btn-sm" onClick={handleCreate} disabled={!canSave || saving}>
                {saving ? 'Adding...' : 'Add Capability'}
              </button>
              <button className="btn btn-outline-secondary btn-sm" onClick={() => setForm(BLANK)} disabled={saving}>
                Clear
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Existing amenities ── */}
      <div className="col-12 col-xl-7">
        <div className="card h-100">
          <div className="card-header d-flex justify-content-between align-items-center">
            <strong>Building Capabilities ({amenities.length})</strong>
            <button className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
          <div className="card-body p-0">
            <div style={{ maxHeight: 520, overflowY: 'auto' }}>
              <table className="table table-sm table-bordered mb-0" style={{ fontSize: 12 }}>
                <thead className="table-light">
                  <tr><th>Label</th><th>ID</th><th>Location</th><th style={{ width: 60 }}></th></tr>
                </thead>
                <tbody>
                  {amenities.length === 0 && (
                    <tr><td colSpan={4} className="text-muted text-center py-3">
                      {loading ? 'Loading...' : 'No capabilities found. Add one on the left.'}
                    </td></tr>
                  )}
                  {amenities.map((a) => (
                    <tr key={a.a}>
                      <td>{a.label || <span className="text-muted">(no label)</span>}</td>
                      <td className="font-monospace" style={{ wordBreak: 'break-all' }}>{localName(a.a)}</td>
                      <td>{a.loc || ''}</td>
                      <td className="text-center">
                        <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{ fontSize: 11 }}
                          onClick={() => handleDelete(a.a)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
