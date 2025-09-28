const { LOG_LEVEL, LogLevel } = require('../constants');

function log(level, ...args) {
  if (LOG_LEVEL >= level) {
    // eslint-disable-next-line no-console
    console.error(...args);
  }
}

// Logs general errors to console
function consoleLogErrors(err, _req, _res, next) {
  log(LogLevel.error, '[error]', err?.stack || err?.message || String(err));
  next(err);
}

// Optionally log MongoDB-specific errors (kept separate for clarity)
function mongodbLogErrors(err, _req, _res, next) {
  const isMongo = err?.name?.includes('Mongo') || err?.codeName || err?.code;
  if (isMongo) {
    log(LogLevel.error, '[mongo]', err);
  }
  next(err);
}

// Send a consistent JSON error response
function errorHandler(err, _req, res, _next) {
  const status = err?.status || 500;
  const message = err?.message || 'Internal Server Error';
  res.status(status).json({ error: message });
}

module.exports = { consoleLogErrors, mongodbLogErrors, errorHandler };
