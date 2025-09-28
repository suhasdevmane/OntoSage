// Small helper to provide a fast ping without re-querying full tables
const { Client } = require('pg');
const { PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE } = require('../constants');

let singleton;
async function getClient() {
	if (!singleton) {
		singleton = new Client({ host: PGHOST, port: PGPORT, user: PGUSER, password: PGPASSWORD, database: PGDATABASE });
		try { await singleton.connect(); } catch (e) { /* ignore here; ping will surface */ }
	}
	return singleton;
}

async function ping() {
	const c = await getClient();
	return c.query('SELECT 1');
}

module.exports = { ping };
