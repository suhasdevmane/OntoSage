const request = require('supertest');

// Spin up the express app directly
let app;
let server;

/** Utility: wait for a condition */
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

beforeAll(async () => {
  process.env.DB_ENGINE = 'postgres';
  process.env.PGHOST = process.env.PGHOST || 'localhost';
  process.env.PGPORT = process.env.PGPORT || '5432';
  process.env.PGUSER = process.env.PGUSER || 'postgres';
  process.env.PGPASSWORD = process.env.PGPASSWORD || 'postgres';
  process.env.PGDATABASE = process.env.PGDATABASE || 'abacws_test';
  process.env.API_KEY = 'test-key';
  app = require('../src/app');
  server = app.listen(0); // ephemeral port
  // Give Postgres init a moment (tables creation)
  await sleep(500);
});

afterAll(async () => {
  try { await server.close(); } catch(_) {}
  try {
    const store = require('../src/api/datastore');
    if (store && store.engine === 'postgres' && typeof store.close === 'function') {
      await store.close();
    }
  } catch(_) {}
});

// Helper to add api key header to a supertest request (agent() returns a fresh request factory)
function authed(r){ return r.set('x-api-key','test-key'); }

async function ensureDevice(agentFactory, name='test_device_A') {
  await authed(agentFactory().post('/api/devices')).send({
    name,
    type: 'sensor',
    floor: 1,
    position: { x: 1, y: 70, z: 1 }
  });
  return name;
}

// We assume an existing table for time-series doesn't exist in test DB.
// Instead we create a temporary table and insert some rows directly via pg client.
const { Client } = require('pg');
let pgClient;

beforeAll(async () => {
  pgClient = new Client({
    host: process.env.PGHOST,
    port: process.env.PGPORT,
    user: process.env.PGUSER,
    password: process.env.PGPASSWORD,
    database: process.env.PGDATABASE,
  });
  await pgClient.connect();
  // Rely on application init to create core tables
  // Create a synthetic readings table
  await pgClient.query(`CREATE TABLE IF NOT EXISTS env_readings (
    sensor_id text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    temperature_c numeric,
    humidity_pct numeric
  );`);
});

afterAll(async () => {
  try { await pgClient.end(); } catch(_) {}
});

describe('Time-series mappings integration', () => {
  const agent = () => request(server);
  let dataSourceId;
  let mappingId;

  test('Create device + data source', async () => {
    const deviceName = await ensureDevice(agent);
    const uniqueName = 'local_'+Date.now();
    const dsRes = await authed(agent().post('/api/datasources')).send({
      name: uniqueName, host: process.env.PGHOST, port: Number(process.env.PGPORT), database: process.env.PGDATABASE, user: process.env.PGUSER, password: process.env.PGPASSWORD, schema: 'public'
    });
    expect(dsRes.status).toBe(201);
    dataSourceId = dsRes.body.id;
    expect(typeof dataSourceId).toBe('number');
  });

  test('List tables + columns', async () => {
    const tblRes = await agent().get(`/api/datasources/${dataSourceId}/tables`);
    expect(tblRes.status).toBe(200);
    expect(Array.isArray(tblRes.body)).toBe(true);
    const colRes = await agent().get(`/api/datasources/${dataSourceId}/columns`).query({ table: 'env_readings' });
    expect(colRes.status).toBe(200);
    expect(Array.isArray(colRes.body)).toBe(true);
  });

  test('Insert sample readings directly', async () => {
    const now = Date.now();
    const rows = [];
    for (let i=0;i<5;i++) {
      rows.push(pgClient.query('INSERT INTO env_readings(sensor_id, recorded_at, temperature_c, humidity_pct) VALUES($1, to_timestamp($2/1000.0), $3, $4)', ['test_device_A', now - (5000 - i*1000), 20 + i, 40 + i*2]));
    }
    await Promise.all(rows);
  });

  test('Create mapping', async () => {
    const res = await authed(agent().post('/api/mappings')).send({
      device_name: 'test_device_A',
      data_source_id: dataSourceId,
      table_name: 'env_readings',
      device_id_column: 'sensor_id',
      device_identifier_value: 'test_device_A',
      timestamp_column: 'recorded_at',
      value_columns: ['temperature_c','humidity_pct'],
      primary_value_column: 'temperature_c',
      range_min: 15,
      range_max: 30,
      color_min: '#1d4ed8',
      color_max: '#ef4444'
    });
    expect(res.status).toBe(201);
    mappingId = res.body.id;
    expect(typeof mappingId).toBe('number');
  });

  test('Fetch timeseries', async () => {
    const to = Date.now();
    const from = to - 60000;
    const res = await agent().get(`/api/mappings/device/test_device_A/timeseries`).query({ from, to });
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.series)).toBe(true);
    expect(res.body.series.length).toBeGreaterThan(0);
    expect(res.body.mapping.device_name).toBe('test_device_A');
  });

  test('Fetch latest batch', async () => {
    const res = await agent().get('/api/latest');
    expect(res.status).toBe(200);
    expect(res.body['test_device_A']).toBeDefined();
    expect(res.body['test_device_A'].primary).toBeDefined();
    expect(res.body['test_device_A'].range_min).toBe(15);
  });

  test('Update mapping', async () => {
    const res = await authed(agent().patch(`/api/mappings/${mappingId}`)).send({ primary_value_column: 'humidity_pct' });
    expect(res.status).toBe(200);
    expect(res.body.primary_value_column).toBe('humidity_pct');
  });

  test('Delete mapping', async () => {
    const res = await authed(agent().delete(`/api/mappings/${mappingId}`));
    expect(res.status).toBe(200);
  });
});
