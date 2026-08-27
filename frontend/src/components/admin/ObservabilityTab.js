import React, { useEffect, useState, useCallback } from 'react';

/**
 * Observability — what this building can actually observe (V6-T11).
 *
 * Reads the SAME coverage schema and the same Reach the conversational
 * observability lane answers from. Not a second computation of the same idea:
 * two copies of one measurement drift, and a portal that disagreed with the chat
 * answer would be worse than no portal, because it would look authoritative
 * while contradicting the system.
 *
 * Every negative shows the step that would change it. A matrix of red cells an
 * operator cannot act on is decoration; "the wiring is already in place, check
 * the feed" is a job.
 */

const STATUS_STYLE = {
  observable: { cls: 'success', label: 'Observable' },
  stale: { cls: 'warning', label: 'Stale' },
  unconnected: { cls: 'info', label: 'Not connected' },
  uninstrumented: { cls: 'secondary', label: 'Not instrumented' },
  unknown: { cls: 'dark', label: 'Unknown' },
};

const CAL_STYLE = {
  calibrated: 'success',
  expired: 'danger',
  unknown: 'secondary',
};

function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  return <span className={`badge bg-${s.cls}`}>{s.label}</span>;
}

export default function ObservabilityTab({ api, headers }) {
  const [matrix, setMatrix] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modality, setModality] = useState('');
  const [status, setStatus] = useState('');
  const [floor, setFloor] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams();
      if (modality) qs.set('modality', modality);
      if (status) qs.set('status', status);
      if (floor) qs.set('floor', floor);
      const [m, c] = await Promise.all([
        fetch(`${api}/api/v1/admin/observability/matrix?${qs.toString()}`, { headers }),
        fetch(`${api}/api/v1/admin/observability/calibration`, { headers }),
      ]);
      const mj = await m.json();
      const cj = await c.json();
      if (!mj.success) throw new Error(mj.error || 'matrix unavailable');
      setMatrix(mj.data);
      // Calibration failing must not blank the matrix: they answer different
      // questions and one being unreadable is not the other being wrong.
      setCalibration(cj.success ? cj.data : { records: [], by_state: {}, error: cj.error });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [api, headers, modality, status, floor]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="d-flex align-items-center mb-3">
        <h4 className="me-3 mb-0">Observability</h4>
        <span className="text-muted small">
          What the building can answer with — read live from its own graph, never from a
          checklist.
        </span>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="row g-2 mb-3">
        <div className="col-auto">
          <select
            className="form-select form-select-sm"
            value={modality}
            onChange={(e) => setModality(e.target.value)}
          >
            <option value="">All modalities</option>
            {(matrix?.modalities || []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="col-auto">
          <select
            className="form-select form-select-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">All states</option>
            {Object.keys(STATUS_STYLE).map((s) => (
              <option key={s} value={s}>
                {STATUS_STYLE[s].label}
              </option>
            ))}
          </select>
        </div>
        <div className="col-auto">
          <input
            className="form-control form-control-sm"
            placeholder="Floor"
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
            style={{ width: 120 }}
          />
        </div>
        <div className="col-auto">
          <button className="btn btn-sm btn-outline-primary" onClick={load} disabled={loading}>
            {loading ? 'Reading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {matrix && (
        <>
          <div className="mb-3">
            {Object.entries(matrix.by_status || {}).map(([k, v]) => (
              <span key={k} className="me-2">
                <StatusBadge status={k} /> <strong>{v}</strong>
              </span>
            ))}
            <span className="text-muted small ms-2">
              {matrix.spaces} spaces × {(matrix.modalities || []).length} modalities ={' '}
              {matrix.cells_total} cells
            </span>
          </div>

          <h6>By modality</h6>
          <div className="table-responsive mb-4" style={{ maxHeight: 320 }}>
            <table className="table table-sm table-striped">
              <thead>
                <tr>
                  <th>Modality</th>
                  {Object.keys(STATUS_STYLE).map((s) => (
                    <th key={s} className="text-end">
                      {STATUS_STYLE[s].label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(matrix.per_modality || {})
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([m, counts]) => (
                    <tr key={m}>
                      <td>{m}</td>
                      {Object.keys(STATUS_STYLE).map((s) => (
                        <td key={s} className="text-end">
                          {counts[s] || 0}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          <h6>
            Cells{' '}
            <span className="text-muted small">
              showing {matrix.cells_shown} of {matrix.cells_matching}
              {matrix.truncated > 0 && ` — ${matrix.truncated} more not shown; narrow the filters`}
            </span>
          </h6>
          <div className="table-responsive mb-4" style={{ maxHeight: 460 }}>
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>Space</th>
                  <th>Modality</th>
                  <th>State</th>
                  <th>Sensor</th>
                  <th>What would change it</th>
                </tr>
              </thead>
              <tbody>
                {(matrix.cells || []).map((c, i) => (
                  <tr key={`${c.space}:${c.modality}:${i}`}>
                    <td className="text-nowrap">{c.space}</td>
                    <td className="text-nowrap">{c.modality}</td>
                    <td>
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="text-nowrap small">
                      <code>{c.sensor || '—'}</code>
                    </td>
                    <td className="small">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h6>Calibration</h6>
      {calibration?.error && (
        <div className="alert alert-warning py-2">
          Calibration records could not be read: {calibration.error}. The coverage matrix above
          is unaffected — they answer different questions.
        </div>
      )}
      {calibration && (
        <>
          <div className="mb-2">
            {Object.entries(calibration.by_state || {}).map(([k, v]) => (
              <span key={k} className="me-2">
                <span className={`badge bg-${CAL_STYLE[k] || 'secondary'}`}>{k}</span>{' '}
                <strong>{v}</strong>
              </span>
            ))}
          </div>
          <p className="text-muted small">{calibration.note}</p>
          <div className="table-responsive" style={{ maxHeight: 360 }}>
            <table className="table table-sm table-striped">
              <thead>
                <tr>
                  <th>Point</th>
                  <th>State</th>
                  <th>Calibrated</th>
                  <th>Due</th>
                  <th>Method</th>
                </tr>
              </thead>
              <tbody>
                {(calibration.records || []).map((r, i) => (
                  <tr key={`${r.point}:${i}`}>
                    <td className="text-nowrap small">
                      <code>{r.point}</code>
                    </td>
                    <td>
                      <span className={`badge bg-${CAL_STYLE[r.state] || 'secondary'}`}>
                        {r.state}
                      </span>
                    </td>
                    <td className="small">{r.calibrated_on || '—'}</td>
                    <td className="small">{r.calibration_due_on || '—'}</td>
                    <td className="small">{r.method || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
