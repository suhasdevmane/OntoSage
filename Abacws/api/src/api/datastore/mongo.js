// Mongo implementation (existing behavior extracted)
const client = require('../database');
const { DEVICE_COLLECTION_PREFIX } = require('../constants');
const { upsertDevice } = require('../devicesFile');

function getDeviceCollection(deviceName) {
  return client.db().collection(`${DEVICE_COLLECTION_PREFIX}_${deviceName}`);
}

async function listDevices() {
  return client.db().collection('devices').find({}).project({ _id: 0 }).toArray();
}

async function getDeviceByName(name) {
  return client.db().collection('devices').findOne({ name }, { projection: { _id: 0 } });
}

async function createDevice(doc) {
  const devicesCol = client.db().collection('devices');
  try { await devicesCol.createIndex({ name: 1 }, { unique: true, name: 'unique_name' }); } catch (_) {}
  await devicesCol.insertOne(doc);
  const created = await devicesCol.findOne({ name: doc.name }, { projection: { _id: 0 } });
  upsertDevice(created);
  return created;
}

async function updateDevice(name, update) {
  const devicesCol = client.db().collection('devices');
  const { value } = await devicesCol.findOneAndUpdate(
    { name },
    { $set: update },
    { returnDocument: 'after', projection: { _id: 0 } }
  );
  if (value) upsertDevice(value);
  return value;
}

async function latestDeviceData(name) {
  const col = getDeviceCollection(name);
  return col.findOne({}, { limit: 1, sort: { timestamp: -1 }, projection: { _id: 0 } });
}

async function insertDeviceData(name, data) {
  const col = getDeviceCollection(name);
  await col.insertOne(data);
  if (!(await col.indexExists('timestamp'))) {
    try { await col.createIndex({ timestamp: 1 }, { name: 'timestamp' }); } catch (_) {}
  }
}

async function deviceHistory(name, from, to, limit = 10000) {
  const col = getDeviceCollection(name);
  return col.find({ timestamp: { $gte: from, $lte: to } }, { sort: { timestamp: -1 }, limit, projection: { _id: 0 } }).toArray();
}

async function deleteDeviceHistory(name) {
  const col = getDeviceCollection(name);
  try { await col.drop(); } catch (_) {}
}

module.exports = {
  engine: 'mongo',
  listDevices,
  getDeviceByName,
  createDevice,
  updateDevice,
  latestDeviceData,
  insertDeviceData,
  deviceHistory,
  deleteDeviceHistory,
};
