const { DB_ENGINE } = require('../constants');
const base = { ...require('./errors'), ...require('./auth') };

if (DB_ENGINE === 'postgres') {
  // We still need real device resolution for Postgres engine (uses unified datastore).
  Object.assign(base, require('./devices'));
  // Query middleware (Mongo-specific filters) can be a no-op for now under Postgres.
  base.queryMiddleware = (_req, _res, next) => next();
} else {
  Object.assign(base, require('./devices'));
  base.queryMiddleware = require('./query');
}

module.exports = base;
