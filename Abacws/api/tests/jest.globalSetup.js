const { execSync, spawn } = require('child_process');
const net = require('net');

function waitForPort(host, port, timeoutMs = 20000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    (function attempt() {
      const socket = net.createConnection({ host, port }, () => {
        socket.destroy();
        resolve();
      });
      socket.on('error', () => {
        socket.destroy();
        if (Date.now() - start > timeoutMs) return reject(new Error(`Timeout waiting for ${host}:${port}`));
        setTimeout(attempt, 500);
      });
    })();
  });
}

module.exports = async () => {
  if (process.env.SKIP_DOCKER) {
    return;
  }
  // Start only postgres service to keep it light
  const composeCwd = process.cwd() + '/../';
  try {
    execSync('docker compose up -d postgres', { stdio: 'inherit', cwd: composeCwd });
  } catch (e) {
    console.error('Failed to start postgres via docker compose', e.message);
    throw e;
  }
  // Wait for TCP port
  await waitForPort('localhost', parseInt(process.env.PGPORT || '5432', 10));
  // Create test database if not exists (idempotent check)
  try {
    const check = execSync('docker compose exec -T postgres psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname=\'abacws_test\'"', { cwd: composeCwd });
    if (!String(check).trim()) {
      execSync('docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE abacws_test;"', { stdio: 'inherit', cwd: composeCwd });
    }
  } catch (e) {
    console.warn('Database existence check failed, attempting create with retry');
    const start = Date.now();
    while (Date.now() - start < 15000) {
      try {
        execSync('docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE abacws_test;"', { stdio: 'inherit', cwd: composeCwd });
        break;
      } catch (err) {
        if (/already exists/i.test(err.message)) break;
        await new Promise(r => setTimeout(r, 1000));
      }
    }
  }
};
