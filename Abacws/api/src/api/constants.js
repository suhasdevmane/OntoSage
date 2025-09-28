const LogLevel = { info: 2, warn: 1, error: 0 };

const PORT = Number(process.env.API_PORT) || 5000;
const PRODUCTION = process.env.PRODUCTION === 'true' || process.env.NODE_ENV === 'production';
const MONGODB_URI = process.env.MONGODB_URI || "mongodb://localhost:27017/abacws";
const API_KEY = process.env.API_KEY || "V3rySecur3Pas3word";
const DEVICE_COLLECTION_PREFIX = "d";

// Database engine selection: 'mongo' (default) | 'postgres' | 'mysql' | 'disabled'
const DB_ENGINE = (process.env.DB_ENGINE || 'mongo').toLowerCase();
// Flag to indicate coordinates have been normalized (legacy offset baked into DB)
const COORDS_NORMALIZED = process.env.COORDS_NORMALIZED === 'true';

// Postgres connection settings (used when DB_ENGINE=postgres)
const PGHOST = process.env.PGHOST || 'localhost';
const PGPORT = Number(process.env.PGPORT) || 5432;
const PGUSER = process.env.PGUSER || 'postgres';
const PGPASSWORD = process.env.PGPASSWORD || 'postgres';
const PGDATABASE = process.env.PGDATABASE || 'abacws';

// MySQL connection settings (used when DB_ENGINE=mysql)
const MYSQL_HOST = process.env.MYSQL_HOST || 'localhost';
const MYSQL_PORT = Number(process.env.MYSQL_PORT) || 3306;
const MYSQL_USER = process.env.MYSQL_USER || 'root';
const MYSQL_PASSWORD = process.env.MYSQL_PASSWORD || 'mysql';
const MYSQL_DATABASE = process.env.MYSQL_DATABASE || 'abacws';

// Set LOG_LEVEL to info if we are not in a production environment, otherwise default to error
const LOG_LEVEL = (!PRODUCTION) ? LogLevel.info : (Number(process.env.LOG_LEVEL) ?? LogLevel.error);

// Set URL_PREFIX to "/api" if we are in a development environment
const URL_PREFIX = "/api";

module.exports = { LogLevel, PORT, PRODUCTION, MONGODB_URI, API_KEY, DEVICE_COLLECTION_PREFIX, LOG_LEVEL, URL_PREFIX, DB_ENGINE, PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, COORDS_NORMALIZED };
