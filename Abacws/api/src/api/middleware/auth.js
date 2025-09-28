const { API_KEY } = require('../constants');

function apiKeyAuth(req, res, next) {
  const header = req.get('x-api-key') || req.query.apiKey || req.query.api_key;
  if (!API_KEY) return next(); // no key configured -> allow
  if (header === API_KEY) return next();
  return res.status(401).json({ error: 'Unauthorized' });
}

module.exports = { apiKeyAuth };
