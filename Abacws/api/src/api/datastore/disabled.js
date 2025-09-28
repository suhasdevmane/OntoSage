// Disabled (offline) datastore adapter
// Reads devices from devices.json and keeps runtime-only history in memory.
const devicesFile = require('../data/devices.json');
const { upsertDevice } = require('../devicesFile');

// Clone initial devices (strip offset already applied in import stage for mongo, here we trust file)
let devices = (devicesFile.devices || []).map(d => ({
  name: d.name,
  type: d.type,
  floor: d.floor,
  position: { ...d.position },
  pinned: !!d.pinned,
}));

// history: { deviceName: [ {..data} ] }
const history = {};

function listDevices() { return Promise.resolve(devices.slice()); }
function getDeviceByName(name) { return Promise.resolve(devices.find(d => d.name === name)); }
async function createDevice(doc) {
  if (devices.find(d => d.name === doc.name)) {
    const err = new Error('duplicate');
    err.code = 'DUPLICATE';
    throw err;
  }
  devices.push(doc);
  upsertDevice(doc);
  return doc;
}
async function updateDevice(name, update) {
  const idx = devices.findIndex(d => d.name === name);
  if (idx === -1) return null;
  devices[idx] = { ...devices[idx], ...update };
  if (update.position) devices[idx].position = { ...update.position };
  upsertDevice(devices[idx]);
  return devices[idx];
}
async function latestDeviceData(name) {
  const arr = history[name];
  if (!arr || !arr.length) return null;
  return arr[arr.length - 1];
}
async function insertDeviceData(name, data) {
  if (!history[name]) history[name] = [];
  history[name].push(data);
}
async function deviceHistory(name, from, to, limit = 10000) {
  const arr = history[name] || [];
  return arr.filter(d => d.timestamp >= from && d.timestamp <= to).slice(-limit).reverse();
}
async function deleteDeviceHistory(name) { history[name] = []; }

module.exports = { engine: 'disabled', listDevices, getDeviceByName, createDevice, updateDevice, latestDeviceData, insertDeviceData, deviceHistory, deleteDeviceHistory };