// Postgres implementation of datastore
// Tables:
//  devices(name PK text, type text, floor int, pos_x numeric, pos_y numeric, pos_z numeric, pinned boolean, created_at timestamptz default now(), updated_at timestamptz default now())
//  device_data(id bigserial PK, device_name text references devices(name) on delete cascade, timestamp bigint, payload jsonb)
// Indexes: device_data(device_name, timestamp DESC)

const { PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE } = require('../constants');
const { upsertDevice } = require('../devicesFile');
const { Client } = require('pg');

let closed = false;
let client; // set after successful connection
function attachErrorHandler(c) {
  c.on('error', (err) => {
    if (closed) return;
    if (err.code === '57P01') return; // admin termination
    if (/terminat(ed|ing) connection/i.test(err.message)) return;
    if (/connection terminated unexpectedly/i.test(err.message)) return;
    if (!closed) console.error('Postgres client error', err);
  });
}

// Retry logic parameters (can be tuned via env if desired later)
const MAX_CONNECT_ATTEMPTS = Number(process.env.PG_MAX_CONNECT_ATTEMPTS) || 30; // ~ (1st 300ms growing to a few seconds)
const INITIAL_DELAY_MS = Number(process.env.PG_INITIAL_DELAY_MS) || 300;
const MAX_DELAY_MS = Number(process.env.PG_MAX_DELAY_MS) || 5000;

let initStarted = false;
let readyResolve; let readyReject;
const ready = new Promise((res, rej) => { readyResolve = res; readyReject = rej; });

function isTransientConnectError(e) {
  if (!e) return false;
  if (e.code === '57P03') return true; // database system is starting up
  if (e.code === 'ECONNREFUSED') return true; // container not up yet
  if (e.code === 'ENOTFOUND') return true; // DNS not ready in network
  if (/the database system is starting up/i.test(e.message)) return true;
  if (/terminat(ed|ing) connection/i.test(e.message)) return true;
  return false;
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function connectWithRetry(attempt = 1, delay = INITIAL_DELAY_MS) {
  if (closed) return;
  // Create a fresh client each attempt to avoid 'already been connected' errors
  const attemptClient = new Client({
    host: PGHOST,
    port: PGPORT,
    user: PGUSER,
    password: PGPASSWORD,
    database: PGDATABASE,
  });
  attachErrorHandler(attemptClient);
  try {
    await attemptClient.connect();
    client = attemptClient; // promote to active client
    if (!closed) console.log(`Postgres connected (attempt ${attempt})`);
    if (!initStarted) {
      initStarted = true;
      try {
        await init();
        if (!closed) console.log('Postgres schema ready');
        readyResolve();
      } catch (e) {
        if (!closed) console.error('Postgres init failed', e);
        readyReject(e);
      }
    }
  } catch (e) {
    // Dispose attempt client (can't reuse)
    try { attemptClient.removeAllListeners(); await attemptClient.end(); } catch(_) {}
    if (closed) return;
    const transient = isTransientConnectError(e);
    if (transient && attempt < MAX_CONNECT_ATTEMPTS) {
      if (!closed) console.warn(`Postgres connect attempt ${attempt} failed (${e.code || e.message}); retrying in ${delay}ms...`);
      await sleep(delay);
      const nextDelay = Math.min(Math.round(delay * 1.5), MAX_DELAY_MS);
      return connectWithRetry(attempt + 1, nextDelay);
    } else {
      if (!closed) console.error('Postgres connection failed (final)', e);
      readyReject(e);
    }
  }
}

// Kick off the retry loop immediately
connectWithRetry();

async function init() {
  // Wait guard in case called erroneously before client set
  if (!client) throw new Error('Client not ready for init');
  await client.query(`CREATE TABLE IF NOT EXISTS devices (
    name text PRIMARY KEY,
    type text,
    floor int NOT NULL,
    pos_x numeric NOT NULL,
    pos_y numeric NOT NULL,
    pos_z numeric NOT NULL,
    pinned boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
  );`);
  await client.query(`CREATE TABLE IF NOT EXISTS device_data (
    id bigserial PRIMARY KEY,
    device_name text NOT NULL REFERENCES devices(name) ON DELETE CASCADE,
    timestamp bigint NOT NULL,
    payload jsonb NOT NULL
  );`);
  await client.query(`CREATE INDEX IF NOT EXISTS idx_device_data_device_time ON device_data(device_name, timestamp DESC);`);
  // External time-series integration tables
  await client.query(`CREATE TABLE IF NOT EXISTS data_sources (
    id serial PRIMARY KEY,
    name text UNIQUE NOT NULL,
    host text NOT NULL,
    port int NOT NULL,
    database text NOT NULL,
    schema text,
    username text,
    password text,
    ssl boolean DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
  );`);
  await client.query(`CREATE TABLE IF NOT EXISTS device_timeseries_mappings (
    id serial PRIMARY KEY,
    device_name text NOT NULL REFERENCES devices(name) ON DELETE CASCADE,
    data_source_id int NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    table_name text NOT NULL,
    device_id_column text NOT NULL,
    device_identifier_value text NOT NULL,
    timestamp_column text NOT NULL,
    value_columns text[] NOT NULL,
    primary_value_column text,
    range_min numeric,
    range_max numeric,
    color_min text,
    color_max text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(device_name, data_source_id)
  );`);

  // Threshold / rules engine table
  await client.query(`CREATE TABLE IF NOT EXISTS device_rules (
    id serial PRIMARY KEY,
    device_name text NOT NULL REFERENCES devices(name) ON DELETE CASCADE,
    source_type text NOT NULL CHECK (source_type IN ('internal','external')),
    field text NOT NULL,
    op text NOT NULL CHECK (op IN ('>','>=','<','<=','=','!=','between','outside')),
    threshold_low numeric NOT NULL,
    threshold_high numeric,
    severity text NOT NULL DEFAULT 'info',
    enabled boolean NOT NULL DEFAULT true,
    description text,
    last_triggered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
  );`);
  await client.query(`CREATE INDEX IF NOT EXISTS idx_device_rules_device ON device_rules(device_name);`);

  // Seed devices from JSON if table empty (skip during tests to keep deterministic fixtures)
  try {
    if (process.env.NODE_ENV !== 'test') {
      const { rows: [{ count }] } = await client.query('SELECT COUNT(*)::int AS count FROM devices');
      if (count === 0) {
        const seed = require('../data/devices.json');
        if (Array.isArray(seed.devices) && seed.devices.length) {
          for (const d of seed.devices) {
            try {
              await client.query(
                'INSERT INTO devices(name,type,floor,pos_x,pos_y,pos_z,pinned) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (name) DO NOTHING',
                [d.name, d.type || null, d.floor, d.position.x, d.position.y, d.position.z, !!d.pinned]
              );
              // Mirror to devices.json in-memory cache for feature parity
              upsertDevice({ name: d.name, type: d.type, floor: d.floor, position: d.position, pinned: !!d.pinned });
            } catch (e) { /* ignore individual insert errors */ }
          }
          const { rows: [{ count: after }] } = await client.query('SELECT COUNT(*)::int AS count FROM devices');
          if (!closed) console.log(`[Postgres] Seeded ${after} devices from devices.json`);
        }
      }
    }
  } catch (e) {
    if (!closed) console.warn('[Postgres] Device seeding skipped due to error:', e.message);
  }
}

function mapRow(r) {
  if (!r) return null;
  return {
    name: r.name,
    type: r.type || undefined,
    floor: Number(r.floor),
    position: { x: Number(r.pos_x), y: Number(r.pos_y), z: Number(r.pos_z) },
    pinned: r.pinned,
  };
}

async function listDevices() {
  await ready;
  const { rows } = await client.query('SELECT * FROM devices ORDER BY name');
  return rows.map(mapRow);
}

async function getDeviceByName(name) {
  await ready;
  const { rows } = await client.query('SELECT * FROM devices WHERE name=$1', [name]);
  return mapRow(rows[0]);
}

async function createDevice(doc) {
  await ready;
  const q = `INSERT INTO devices(name,type,floor,pos_x,pos_y,pos_z,pinned) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *`;
  const values = [doc.name, doc.type || null, doc.floor, doc.position.x, doc.position.y, doc.position.z, doc.pinned];
  const { rows } = await client.query(q, values);
  const mapped = mapRow(rows[0]);
  upsertDevice(mapped);
  return mapped;
}

async function updateDevice(name, update) {
  await ready;
  const fields = [];
  const values = [];
  let i = 1;
  if (update.type !== undefined) { fields.push(`type=$${i++}`); values.push(update.type); }
  if (update.floor !== undefined) { fields.push(`floor=$${i++}`); values.push(update.floor); }
  if (update.position !== undefined) {
    fields.push(`pos_x=$${i++}`, `pos_y=$${i++}`, `pos_z=$${i++}`);
    values.push(update.position.x, update.position.y, update.position.z);
  }
  if (update.pinned !== undefined) { fields.push(`pinned=$${i++}`); values.push(update.pinned); }
  if (!fields.length) return null;
  fields.push(`updated_at=now()`);
  values.push(name);
  const q = `UPDATE devices SET ${fields.join(',')} WHERE name=$${i} RETURNING *`;
  const { rows } = await client.query(q, values);
  const mapped = mapRow(rows[0]);
  if (mapped) upsertDevice(mapped);
  return mapped;
}

async function latestDeviceData(name) {
  await ready;
  const { rows } = await client.query('SELECT payload, timestamp FROM device_data WHERE device_name=$1 ORDER BY timestamp DESC LIMIT 1', [name]);
  if (!rows[0]) return null;
  return { ...rows[0].payload, timestamp: Number(rows[0].timestamp) };
}

async function insertDeviceData(name, data) {
  await ready;
  await client.query('INSERT INTO device_data(device_name, timestamp, payload) VALUES($1,$2,$3)', [name, data.timestamp, data]);
}

async function deviceHistory(name, from, to, limit = 10000) {
  await ready;
  const { rows } = await client.query('SELECT payload, timestamp FROM device_data WHERE device_name=$1 AND timestamp BETWEEN $2 AND $3 ORDER BY timestamp DESC LIMIT $4', [name, from, to, limit]);
  return rows.map(r => ({ ...r.payload, timestamp: Number(r.timestamp) }));
}

async function deleteDeviceHistory(name) {
  await ready;
  await client.query('DELETE FROM device_data WHERE device_name=$1', [name]);
}

// =============================
// External Time-Series Support
// =============================

// Data Sources CRUD
async function listDataSources() {
  await ready;
  const { rows } = await client.query('SELECT id, name, host, port, database, schema, ssl, created_at FROM data_sources ORDER BY id');
  return rows;
}

async function createDataSource(ds) {
  await ready;
  const q = `INSERT INTO data_sources(name, host, port, database, schema, username, password, ssl)
             VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, name, host, port, database, schema, ssl, created_at`;
  const values = [ds.name, ds.host, ds.port, ds.database, ds.schema || null, ds.username || null, ds.password || null, !!ds.ssl];
  const { rows } = await client.query(q, values);
  return rows[0];
}

async function updateDataSource(id, patch) {
  await ready;
  const fields = [];
  const values = [];
  let i = 1;
  const allow = ['name','host','port','database','schema','username','password','ssl'];
  for (const key of allow) {
    if (patch[key] !== undefined) { fields.push(`${key}=$${i++}`); values.push(patch[key]); }
  }
  if (!fields.length) return null;
  values.push(id);
  const q = `UPDATE data_sources SET ${fields.join(',')} WHERE id=$${i} RETURNING id, name, host, port, database, schema, ssl, created_at`;
  const { rows } = await client.query(q, values);
  return rows[0] || null;
}

async function deleteDataSource(id) {
  await ready;
  // Prevent delete if mappings exist
  const { rows } = await client.query('SELECT 1 FROM device_timeseries_mappings WHERE data_source_id=$1 LIMIT 1', [id]);
  if (rows.length) return { error: 'Data source in use' };
  await client.query('DELETE FROM data_sources WHERE id=$1', [id]);
  return { ok: true };
}

// Mappings CRUD
async function listDeviceMappings() {
  await ready;
  const { rows } = await client.query(`SELECT * FROM device_timeseries_mappings ORDER BY id`);
  return rows;
}

async function createDeviceMapping(m) {
  await ready;
  const q = `INSERT INTO device_timeseries_mappings(
    device_name, data_source_id, table_name, device_id_column, device_identifier_value,
    timestamp_column, value_columns, primary_value_column, range_min, range_max, color_min, color_max)
    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
    RETURNING *`;
  const vals = [
    m.device_name, m.data_source_id, m.table_name, m.device_id_column, m.device_identifier_value,
    m.timestamp_column, m.value_columns, m.primary_value_column || null, m.range_min || null, m.range_max || null,
    m.color_min || null, m.color_max || null
  ];
  const { rows } = await client.query(q, vals);
  return rows[0];
}

async function updateDeviceMapping(id, patch) {
  await ready;
  const allow = ['device_name','data_source_id','table_name','device_id_column','device_identifier_value','timestamp_column','value_columns','primary_value_column','range_min','range_max','color_min','color_max'];
  const fields = []; const values = []; let i = 1;
  for (const key of allow) {
    if (patch[key] !== undefined) { fields.push(`${key}=$${i++}`); values.push(patch[key]); }
  }
  if (!fields.length) return null;
  values.push(id);
  const q = `UPDATE device_timeseries_mappings SET ${fields.join(',')} WHERE id=$${i} RETURNING *`;
  const { rows } = await client.query(q, values);
  return rows[0] || null;
}

async function deleteDeviceMapping(id) {
  await ready;
  await client.query('DELETE FROM device_timeseries_mappings WHERE id=$1', [id]);
  return { ok: true };
}

// Introspection helpers (basic)
async function listTablesForDataSource(id) {
  await ready;
  const { rows } = await client.query('SELECT * FROM data_sources WHERE id=$1', [id]);
  if (!rows[0]) return null;
  // For now, reuse the existing main connection (assumes same server); future: separate client per DS
  const schema = rows[0].schema || 'public';
  const q = `SELECT table_name FROM information_schema.tables WHERE table_schema=$1 ORDER BY table_name`;
  const { rows: t } = await client.query(q, [schema]);
  return t.map(r => r.table_name);
}

async function listColumnsForDataSourceTable(id, table) {
  await ready;
  const { rows } = await client.query('SELECT * FROM data_sources WHERE id=$1', [id]);
  if (!rows[0]) return null;
  const schema = rows[0].schema || 'public';
  const q = `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position`;
  const { rows: c } = await client.query(q, [schema, table]);
  return c;
}

// Verify mapping: run a sample row fetch using provided details (without persisting anything)
async function verifyDeviceMapping(sample) {
  await ready;
  // sample expects: data_source_id, table_name, device_id_column, device_identifier_value, timestamp_column, value_columns[]
  const required = ['data_source_id','table_name','device_id_column','device_identifier_value','timestamp_column','value_columns'];
  for (const r of required) { if (sample[r] === undefined || sample[r] === null) return { error: `Missing ${r}` }; }
  if (!Array.isArray(sample.value_columns) || !sample.value_columns.length) return { error: 'value_columns must be non-empty array' };
  const { rows } = await client.query('SELECT * FROM data_sources WHERE id=$1', [sample.data_source_id]);
  if(!rows[0]) return { error: 'data_source not found' };
  const ds = rows[0];
  const schema = ds.schema || 'public';
  const cols = sample.value_columns.map(c => `"${c}"`).join(', ');
  const sql = `SELECT ${cols}, EXTRACT(EPOCH FROM "${sample.timestamp_column}")*1000 AS ts
               FROM ${schema}."${sample.table_name}"
               WHERE "${sample.device_id_column}" = $1
               ORDER BY "${sample.timestamp_column}" DESC
               LIMIT 5`;
  try {
    const { rows: result } = await client.query(sql, [sample.device_identifier_value]);
    return { ok: true, rows: result, sql };
  } catch (e) {
    return { error: e.message, sql };
  }
}

// Time series fetch for a single device mapping (window)
async function fetchDeviceTimeseries(deviceName, fromTs, toTs, limit = 2000) {
  await ready;
  const { rows: maps } = await client.query(`SELECT m.*, ds.schema AS ds_schema
    FROM device_timeseries_mappings m
    JOIN data_sources ds ON m.data_source_id = ds.id
    WHERE m.device_name=$1`, [deviceName]);
  if (!maps.length) return { series: [] };
  const map = maps[0];
  const schema = map.ds_schema || 'public';
  const cols = map.value_columns.map(c => `"${c}"`).join(', ');
  const sql = `SELECT EXTRACT(EPOCH FROM "${map.timestamp_column}")*1000 AS ts, ${cols}
               FROM ${schema}."${map.table_name}" 
               WHERE "${map.device_id_column}" = $1 AND "${map.timestamp_column}" BETWEEN TO_TIMESTAMP($2/1000.0) AND TO_TIMESTAMP($3/1000.0)
               ORDER BY "${map.timestamp_column}" ASC
               LIMIT $4`;
  const { rows } = await client.query(sql, [map.device_identifier_value, fromTs, toTs, limit]);
  return { mapping: map, series: rows };
}

// Batch latest values across all mappings
async function fetchLatestForAllMappings(maxLookbackDays = 7) {
  await ready;
  const { rows: mappings } = await client.query(`SELECT m.*, ds.schema AS ds_schema
    FROM device_timeseries_mappings m
    JOIN data_sources ds ON m.data_source_id = ds.id`);
  if (!mappings.length) return {};
  // Group by table / columns signature to reduce queries
  const groups = new Map();
  for (const m of mappings) {
    const key = [m.data_source_id, m.table_name, m.device_id_column, m.timestamp_column, m.value_columns.join('|')].join('::');
    if (!groups.has(key)) groups.set(key, { meta: m, list: [] });
    groups.get(key).list.push(m);
  }
  const result = {};
  for (const g of groups.values()) {
    const { meta, list } = g;
    const schema = meta.ds_schema || 'public';
    const ids = list.map(m => m.device_identifier_value);
    const cols = meta.value_columns.map(c => `"${c}"`).join(', ');
    const sql = `WITH ranked AS (
      SELECT "${meta.device_id_column}" AS device_id,
             EXTRACT(EPOCH FROM "${meta.timestamp_column}")*1000 AS ts,
             ${cols},
             ROW_NUMBER() OVER (PARTITION BY "${meta.device_id_column}" ORDER BY "${meta.timestamp_column}" DESC) rn
      FROM ${schema}."${meta.table_name}" 
      WHERE "${meta.timestamp_column}" > NOW() - INTERVAL '${maxLookbackDays} days'
        AND "${meta.device_id_column}" = ANY($1)
    ) SELECT * FROM ranked WHERE rn=1`;
    const { rows } = await client.query(sql, [ids]);
    for (const row of rows) {
      const mapping = list.find(m => m.device_identifier_value === row.device_id);
      if (!mapping) continue;
      const values = {};
      for (const c of meta.value_columns) values[c] = row[c];
      result[mapping.device_name] = {
        timestamp: Number(row.ts),
        values,
        primary: mapping.primary_value_column ? values[mapping.primary_value_column] : undefined,
        mappingId: mapping.id,
        range_min: mapping.range_min != null ? Number(mapping.range_min) : null,
        range_max: mapping.range_max != null ? Number(mapping.range_max) : null,
        color_min: mapping.color_min,
        color_max: mapping.color_max,
      };
    }
  }
  return result;
}

// =============================
// Rules / Thresholds
// =============================

async function listRules() {
  await ready; const { rows } = await client.query('SELECT * FROM device_rules ORDER BY id'); return rows;
}

async function listRulesForDevice(deviceName) {
  await ready; const { rows } = await client.query('SELECT * FROM device_rules WHERE device_name=$1 AND enabled=true ORDER BY id', [deviceName]); return rows;
}

async function getRule(id) { await ready; const { rows } = await client.query('SELECT * FROM device_rules WHERE id=$1', [id]); return rows[0]||null; }

function validateRulePayload(r, partial=false) {
  const required = ['device_name','source_type','field','op','threshold_low'];
  if(!partial) {
    for(const k of required){ if(r[k]===undefined) return `Missing field '${k}'`; }
  }
  if(r.source_type && !['internal','external'].includes(r.source_type)) return 'Invalid source_type';
  if(r.op && !['>','>=','<','<=','=','!=','between','outside'].includes(r.op)) return 'Invalid op';
  if(r.op && (r.op==='between' || r.op==='outside') && (r.threshold_high===undefined && !partial)) return 'threshold_high required for between/outside';
  return null;
}

async function createRule(payload) {
  await ready; const err = validateRulePayload(payload,false); if(err) return { error: err };
  const q = `INSERT INTO device_rules(device_name,source_type,field,op,threshold_low,threshold_high,severity,enabled,description)
             VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`;
  const vals = [payload.device_name, payload.source_type, payload.field, payload.op, payload.threshold_low, payload.threshold_high||null, payload.severity||'info', payload.enabled!==false, payload.description||null];
  const { rows } = await client.query(q, vals); return rows[0];
}

async function updateRule(id, patch) {
  await ready; const err = validateRulePayload(patch,true); if(err) return { error: err };
  const allow = ['device_name','source_type','field','op','threshold_low','threshold_high','severity','enabled','description'];
  const sets=[]; const vals=[]; let i=1;
  for(const k of allow){ if(patch[k]!==undefined){ sets.push(`${k}=$${i++}`); vals.push(patch[k]); } }
  if(!sets.length) return getRule(id);
  sets.push(`updated_at=now()`);
  vals.push(id);
  const q = `UPDATE device_rules SET ${sets.join(',')} WHERE id=$${i} RETURNING *`;
  const { rows } = await client.query(q, vals); return rows[0]||null;
}

async function deleteRule(id) { await ready; await client.query('DELETE FROM device_rules WHERE id=$1',[id]); return { ok: true }; }

function compare(op, value, low, high){
  switch(op){
    case '>': return value>low;
    case '>=': return value>=low;
    case '<': return value<low;
    case '<=': return value<=low;
    case '=': return value===low;
    case '!=': return value!==low;
    case 'between': return value>=low && value<=high;
    case 'outside': return value<low || value>high;
    default: return false;
  }
}

function extractInternalField(payload, field){
  if(!payload) return undefined; const raw = payload[field];
  if(raw==null) return undefined;
  if(typeof raw==='object' && raw.value!==undefined){ const n = Number(raw.value); return Number.isNaN(n)?undefined:n; }
  const n = Number(raw); return Number.isNaN(n)?undefined:n;
}

function extractExternalField(entry, field){
  if(!entry) return undefined; const raw = entry.values ? entry.values[field] : undefined; if(raw==null) return undefined; const n = Number(raw); return Number.isNaN(n)?undefined:n;
}

async function evaluateRulesForDevice(deviceName){
  await ready;
  const rules = await listRulesForDevice(deviceName);
  if(!rules.length) return [];
  const internal = await latestDeviceData(deviceName); // { ...payload }
  // external batch fetch (reuse aggregator for all, then pick device)
  let externalAll = {};
  try { externalAll = await fetchLatestForAllMappings(); } catch(_) {}
  const external = externalAll[deviceName];
  const ts = Date.now();
  const triggered=[];
  for(const r of rules){
    let current;
    if(r.source_type==='internal') current = extractInternalField(internal, r.field);
    else current = extractExternalField(external, r.field);
    if(current===undefined) continue;
    if(compare(r.op, current, Number(r.threshold_low), r.threshold_high!=null? Number(r.threshold_high): undefined)){
      triggered.push({ id: r.id, device_name: r.device_name, field: r.field, op: r.op, threshold_low: Number(r.threshold_low), threshold_high: r.threshold_high!=null? Number(r.threshold_high): null, severity: r.severity, value: current, source_type: r.source_type, description: r.description, timestamp: ts });
      // async update last_triggered
      client.query('UPDATE device_rules SET last_triggered_at=now() WHERE id=$1', [r.id]).catch(()=>{});
    }
  }
  return triggered;
}

// Final export object including time-series functions
module.exports = {
  engine: 'postgres',
  // Expose readiness promise (internal use / potential future health gating)
  ready,
  listDevices,
  getDeviceByName,
  createDevice,
  updateDevice,
  latestDeviceData,
  insertDeviceData,
  deviceHistory,
  deleteDeviceHistory,
  listDataSources,
  createDataSource,
  updateDataSource,
  deleteDataSource,
  listDeviceMappings,
  createDeviceMapping,
  updateDeviceMapping,
  deleteDeviceMapping,
  listTablesForDataSource,
  listColumnsForDataSourceTable,
  verifyDeviceMapping,
  fetchDeviceTimeseries,
  fetchLatestForAllMappings,
  // rules
  listRules,
  listRulesForDevice,
  getRule,
  createRule,
  updateRule,
  deleteRule,
  evaluateRulesForDevice,
  migrateLegacyCoordinates: async (dryRun = false) => {
    await ready;
    const { rows } = await client.query('SELECT name, pos_x, pos_y, pos_z FROM devices');
    const candidates = rows.filter(r => Number(r.pos_x) < 0 && Number(r.pos_z) > 0);
    if(!candidates.length) return { changed: 0, message: 'No legacy candidates found' };
    if(dryRun) return { changed: candidates.length, sample: candidates.slice(0,5) };
    for(const r of candidates){
      const nx = Number(r.pos_x) + 160;
      const nz = Number(r.pos_z) - 120;
      await client.query('UPDATE devices SET pos_x=$1, pos_z=$2, updated_at=now() WHERE name=$3', [nx, nz, r.name]);
    }
    return { changed: candidates.length };
  },
  close: async () => { try { closed = true; await client.end(); } catch(_) {} },
};
