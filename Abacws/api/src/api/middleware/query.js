const client = require('../database');

// Builds a simple Mongo filter for devices collection from query params
function buildDeviceFilter(q) {
  const filter = {};
  if (q.name) filter.name = { $in: String(q.name).split(',').map((s) => s.trim()) };
  if (q.type) filter.type = { $in: String(q.type).split(',').map((s) => s.trim()) };
  if (q.floor) filter.floor = { $in: String(q.floor).split(',').map((s) => Number(s.trim())) };
  if (q.has) filter[`features.${q.has}`] = { $exists: true }; // if your schema stores feature map
  return filter;
}

async function queryMiddleware(req, res, next) {
  try {
    const { from, to } = req.query;
    const baseFilter = buildDeviceFilter(req.query);
    // For now, only return device info matching the base filter
    const devices = await client
      .db()
      .collection('devices')
      .find(baseFilter, { projection: { _id: 0 } })
      .toArray();

    // Attach time range if provided for downstream consumers
    res.locals.devices = devices;
    res.locals.range = {
      from: from ? Number(from) : undefined,
      to: to ? Number(to) : undefined,
    };
    next();
  } catch (err) {
    next(err);
  }
}

module.exports = queryMiddleware;
