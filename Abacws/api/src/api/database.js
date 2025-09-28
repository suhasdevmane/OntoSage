const { MongoClient } = require('mongodb');
const { MONGODB_URI } = require('./constants');
const devicesFile = require("./data/devices.json");

// Connect to database
const client = new MongoClient(MONGODB_URI);
client.connect()
  .then(() => {
    console.log("Database connected...");
  })
  .catch((reason) => {
    console.error(reason);
  });

// Import devices into the database (only if empty)
async function importDevices() {
  const existing = await client.db().collection("devices").countDocuments();
  if (existing > 0) {
    return; // do not override existing devices
  }
  const offset = devicesFile.offset;
  const devices = devicesFile.devices;

  // Apply offset and add any attributes we need here
  devices.forEach((device) => {
    device.position.x -= offset.x;
    device.position.y -= offset.y;
    device.position.z -= offset.z;
  });

  // Insert new ones
  return await client.db().collection("devices").insertMany(devices);
}

// Call function and log whether it is successful
importDevices()
  .then(() => {
    console.log("Devices import successful");
  })
  .catch((err) => {
    console.log(`Device import failed with '${err}'`);
  });

module.exports = client;
