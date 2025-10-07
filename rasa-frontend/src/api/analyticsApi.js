// Centralized API client for analytics service endpoints
// Adjust BASE if behind gateway / reverse proxy.
const BASE = process.env.REACT_APP_ANALYTICS_BASE || 'http://localhost:8080/analytics';

async function jsonFetch(url, options={}) {
  const res = await fetch(url, { headers:{'Content-Type':'application/json'}, ...options });
  let data = null;
  try { data = await res.json(); } catch(_) { /* ignore */ }
  if(!res.ok) {
    const err = new Error((data && (data.error||data.message)) || `HTTP ${res.status}`);
    err.status = res.status; err.payload = data; throw err;
  }
  return data;
}

export const listFunctions = () => jsonFetch(`${BASE}/functions`);
export const listSimple = () => jsonFetch(`${BASE}/list`);
export const validateFunction = (code) => jsonFetch(`${BASE}/validate_function`, { method:'POST', body: JSON.stringify({ code })});
export const addFunction = (payload) => jsonFetch(`${BASE}/add_function`, { method:'POST', body: JSON.stringify(payload)});
export const testRun = ({ functionName, payload, params }) => jsonFetch(`${BASE}/test_run`, { method:'POST', body: JSON.stringify({ function: functionName, payload, params })});
export const runAnalysis = (payload) => jsonFetch(`${BASE}/run`, { method:'POST', body: JSON.stringify(payload)});
export const listSensors = () => jsonFetch(`${BASE}/sensors`);

// Helper: build a sample payload from selected sensor names.
export function buildSamplePayload(sensorNames=[]) {
  // Produces nested structure similar to canonical analytics payload { sensorIndex: { Sensor_Name: { timeseries_data: [...] }}}
  const now = new Date();
  const ts = (d) => d.toISOString().replace('T',' ').substring(0,19);
  const base = {};
  sensorNames.forEach((name, idx) => {
    base[String(idx+1)] = { [name]: { timeseries_data: [
      { datetime: ts(new Date(now.getTime()-3600*1000)), reading_value: 10+idx },
      { datetime: ts(now), reading_value: 11+idx }
    ]}};
  });
  return base;
}

const analyticsApi = {
  listFunctions,
  listSimple,
  validateFunction,
  addFunction,
  testRun,
  runAnalysis,
  listSensors,
  buildSamplePayload,
};

export default analyticsApi;
