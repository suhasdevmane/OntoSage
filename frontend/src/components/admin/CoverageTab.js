import React, { useState } from 'react';

const SAMPLE_QUESTIONS = [
  "What is the current temperature in Zone 3?",
  "How many CO2 sensors are on floor 2?",
  "Which rooms have occupancy sensors?",
  "What is the average humidity on floor 1?",
  "Show me all air quality sensors",
  "What equipment is in the server room?",
  "How many sensors are there in total?",
  "Which zones had high CO2 last week?",
  "What is the energy consumption trend?",
  "Are there any anomalous temperature readings?",
];

export default function CoverageTab({ api, headers }) {
  const [questions, setQuestions] = useState(SAMPLE_QUESTIONS.join('\n'));
  const [sessionId] = useState(`coverage-test-${Date.now()}`);
  const [results, setResults] = useState([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);

  const runCoverage = async () => {
    const qs = questions.split('\n').map(q => q.trim()).filter(Boolean);
    if (qs.length === 0) return;
    setRunning(true);
    setResults([]);
    setProgress(0);

    const newResults = [];
    for (let i = 0; i < qs.length; i++) {
      const q = qs[i];
      const t0 = Date.now();
      try {
        const r = await fetch(`${api}/chat`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ message: q, session_id: `${sessionId}-${i}` }),
        });
        const d = await r.json();
        const latency = Date.now() - t0;
        const response = d.response || d.data?.response || '';
        const answerable = response.length > 20 &&
          !response.toLowerCase().includes("don't have") &&
          !response.toLowerCase().includes("not available") &&
          !response.toLowerCase().includes("cannot find") &&
          !response.toLowerCase().includes("no data");
        newResults.push({ question: q, answerable, latency, intent: d.intent || d.data?.intent || '?', snippet: response.substring(0, 120), error: null });
      } catch (e) {
        newResults.push({ question: q, answerable: false, latency: Date.now()-t0, intent: '?', snippet: '', error: String(e) });
      }
      setResults([...newResults]);
      setProgress(Math.round(((i+1)/qs.length)*100));
    }
    setRunning(false);
  };

  const exportCsv = () => {
    const rows = ['question,answerable,intent,latency_ms,snippet'];
    results.forEach(r => {
      rows.push(`"${r.question.replace(/"/g,'""')}",${r.answerable},${r.intent},${r.latency},"${(r.snippet||'').replace(/"/g,'""')}"`);
    });
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'question_coverage.csv'; a.click();
  };

  const answerable = results.filter(r => r.answerable).length;
  const pct = results.length > 0 ? Math.round(answerable/results.length*100) : 0;

  return (
    <div>
      <h5>Question Coverage Dashboard</h5>
      <p className="text-muted small">
        Run a batch of questions against the live system and measure how many are answered vs. deflected.
        Use before/after adding a data source to prove coverage improvement.
      </p>

      <div className="row g-4 mb-3">
        <div className="col-12 col-lg-5">
          <label className="form-label small">Questions (one per line)</label>
          <textarea className="form-control font-monospace" rows={14} value={questions}
            onChange={e => setQuestions(e.target.value)} style={{fontSize:12}} />
          <div className="d-flex gap-2 mt-2">
            <button className="btn btn-primary btn-sm" onClick={runCoverage} disabled={running || !questions.trim()}>
              {running ? `Running... ${progress}%` : 'Run Coverage Test'}
            </button>
            {results.length > 0 && (
              <button className="btn btn-outline-secondary btn-sm" onClick={exportCsv}>Export CSV</button>
            )}
          </div>
        </div>

        {results.length > 0 && (
          <div className="col-12 col-lg-7">
            <div className="d-flex gap-3 mb-3 flex-wrap">
              <div className="card text-center" style={{minWidth:100}}>
                <div className="card-body py-2">
                  <div className="fs-2 fw-bold text-success">{pct}%</div>
                  <div className="small text-muted">Answerable</div>
                </div>
              </div>
              <div className="card text-center" style={{minWidth:100}}>
                <div className="card-body py-2">
                  <div className="fs-2 fw-bold">{results.length}</div>
                  <div className="small text-muted">Total</div>
                </div>
              </div>
              <div className="card text-center" style={{minWidth:100}}>
                <div className="card-body py-2">
                  <div className="fs-2 fw-bold text-success">{answerable}</div>
                  <div className="small text-muted">Answered</div>
                </div>
              </div>
              <div className="card text-center" style={{minWidth:100}}>
                <div className="card-body py-2">
                  <div className="fs-2 fw-bold text-danger">{results.length - answerable}</div>
                  <div className="small text-muted">Deflected</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {results.length > 0 && (
        <div style={{maxHeight:380,overflowY:'auto'}}>
          <table className="table table-sm table-bordered" style={{fontSize:12}}>
            <thead className="table-light sticky-top">
              <tr><th style={{width:30}}>#</th><th>Question</th><th style={{width:80}}>Intent</th><th style={{width:70}}>Answerable</th><th style={{width:70}}>Latency</th><th>Response snippet</th></tr>
            </thead>
            <tbody>
              {results.map((r,i) => (
                <tr key={i} className={r.answerable ? '' : 'table-warning'}>
                  <td>{i+1}</td>
                  <td style={{maxWidth:200,wordBreak:'break-word'}}>{r.question}</td>
                  <td><span className="badge bg-secondary" style={{fontSize:10}}>{r.intent}</span></td>
                  <td className="text-center">
                    <span className={`badge bg-${r.answerable?'success':'danger'}`}>{r.answerable?'Yes':'No'}</span>
                  </td>
                  <td>{r.latency}ms</td>
                  <td style={{fontSize:11,color:'#555',maxWidth:200,wordBreak:'break-word'}}>{r.snippet || r.error || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
