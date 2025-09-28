// Unified datastore abstraction switching between Mongo and Postgres
// Provides device and device data operations while preserving existing API contract

const { DB_ENGINE } = require('../constants');

function select() {
	switch (DB_ENGINE) {
		case 'postgres':
			return require('./postgres');
		case 'mysql':
			return require('./mysql');
		case 'disabled':
		case 'off':
		case 'none':
			return require('./disabled');
		case 'mongo':
		default:
			return require('./mongo');
	}
}

module.exports = select();
