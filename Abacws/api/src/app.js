const express = require("express");
const api = require("./api");
const { PORT, URL_PREFIX } = require('./api/constants');
const store = require('./api/datastore');

const app = express();

// Simple process health endpoint (does not depend on DB)
app.get('/health', async (_req, res) => {
  let db = { engine: store.engine, status: 'ok' };
  if (store.engine === 'postgres') {
    try { await require('./api/datastore/postgresPing').ping(); } catch (e) { db.status = 'error'; db.error = e.message; }
  }
  res.status(200).json({ status: 'ok', db });
});

app.get('/health/db', async (_req, res) => {
  let status = { engine: store.engine };
  if (store.engine === 'postgres') {
    try { await require('./api/datastore/postgresPing').ping(); status.status = 'ok'; }
    catch (e) { status.status = 'error'; status.error = e.message; }
  } else if (store.engine === 'mongo') {
    try { const client = require('./api/database'); await client.db().command({ ping: 1 }); status.status = 'ok'; }
    catch (e) { status.status = 'error'; status.error = e.message; }
  } else {
    status.status = 'disabled';
  }
  res.status(200).json(status);
});

app.use(URL_PREFIX, api);

// Only start server if invoked directly (not when required for tests)
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`API is listening on '${PORT}'...`);
  });
}

module.exports = app;
