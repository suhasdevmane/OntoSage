const { execSync } = require('child_process');

module.exports = async () => {
  try {
    const store = require('../src/api/datastore');
    if (store && store.engine === 'postgres' && typeof store.close === 'function') {
      await store.close();
    }
  } catch(_) {}
  if (process.env.SKIP_DOCKER || process.env.KEEP_DOCKER) return;
  try {
    execSync('docker compose stop postgres', { stdio: 'inherit', cwd: process.cwd() + '/../' });
  } catch (e) {
    console.warn('Teardown warning:', e.message);
  }
};
