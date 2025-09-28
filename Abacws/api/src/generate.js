// Script to generate random data for the last 24 hours
const { exit } = require("process");
const { DEVICE_COLLECTION_PREFIX } = require("./api/constants");
const client = require("./api/database");

const FROM_TIME = Date.now() - (24*60*60*1000);
const TO_TIME = Date.now();
const INTERVAL = 60*1000;

const args = process.argv.slice(2);

function noisySineWave(length, amp=1, freq=1, noise=0.2) {
  const result = new Array(length);
  for (let i = 0; i < result.length; i++) {
    result[i] = (amp * Math.sin(freq*(i/180)));
    result[i] = result[i] + (Math.random() * noise) - noise/2;
  }
  return result;
}

function squareWave(length, period, dutyCycle=0.5) {
  const result = new Array(length);
  for (let i = 0; i < result.length; i++) {
    if (i % period > period * dutyCycle) {
      result[i] = 1; continue;
    }
    result[i] = 0;
  }
  return result;
}

async function generateData(name) {
  const length = (TO_TIME-FROM_TIME)/INTERVAL;
  const temperature = noisySineWave(length, 5, 1, 1).map(v => Number((v + 20).toFixed(2)));
  const lightLevel = squareWave(length, length/10).map(v => (v*9000)+1000);
  const humidity = noisySineWave(length, 5, 5, 10).map(v => Number((v + 70).toFixed(0)));
  const CO2 = noisySineWave(length, 50, 20, 40).map(v => Number((v + 440).toFixed(0)));

  const collection = client.db().collection(`${DEVICE_COLLECTION_PREFIX}_${name}`);
  try { await collection.drop(); } catch (e) {}
  const temp = [];

  for (let i = 0; i < length; i++) {
    const timestamp = (INTERVAL * i) + FROM_TIME;
    temp.push({
      timestamp,
      temperature: { value: temperature[i], units: "°C" },
      "light level": { value: lightLevel[i], units: "lux" },
      humidity: { value: humidity[i], units: "%" },
      CO2: { value: CO2[i], units: "ppm" },
    });
  }

  await collection.createIndex({timestamp: 1}, {name: "timestamp"});
  await collection.insertMany(temp);
}

async function main(names) {
  for (const name of names) {
    await generateData(name);
    console.log(`Data created for '${name}'`);
  }
}

main(args)
  .then(() => { console.log("Done"); exit(0); })
  .catch(() => { console.log("Failed"); exit(1); });
