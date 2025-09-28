const fs = require('fs');
const path = require('path');

const FILE_PATH = path.resolve(__dirname, 'data', 'devices.json');

function readJson() {
  const text = fs.readFileSync(FILE_PATH, 'utf-8');
  return JSON.parse(text);
}

function writeJson(obj) {
  const text = JSON.stringify(obj, null, 2);
  fs.writeFileSync(FILE_PATH, text, 'utf-8');
}

function toFilePosition(dbPos, offset) {
  return {
    x: Number(dbPos.x) + Number(offset.x),
    y: Number(dbPos.y) + Number(offset.y),
    z: Number(dbPos.z) + Number(offset.z),
  };
}

/**
 * Update or insert a device in devices.json, adjusting position back by the offset so the file remains consistent.
 * @param {{name:string, type?:string, floor?:number, pinned?:boolean, position:{x:number,y:number,z:number}}} device
 */
function upsertDevice(device) {
  try {
    const json = readJson();
    const { offset } = json;
    const devices = Array.isArray(json.devices) ? json.devices : [];
    const idx = devices.findIndex((d) => d.name === device.name);
    const filePos = toFilePosition(device.position, offset);
    const toWrite = {
      name: device.name,
      type: device.type,
      floor: device.floor,
      position: filePos,
    };
    // Preserve pinned if present
    if (typeof device.pinned === 'boolean') toWrite.pinned = device.pinned;

    if (idx >= 0) {
      devices[idx] = { ...devices[idx], ...toWrite };
    } else {
      devices.push(toWrite);
    }
    json.devices = devices;
    writeJson(json);
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('[devicesFile] Failed to upsert device into devices.json', e);
  }
}

module.exports = { upsertDevice };
