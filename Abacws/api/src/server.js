const app = require('./app');
const { PORT } = require('./api/constants');

app.listen(PORT, () => {
  console.log(`API is listening on '${PORT}'...`);
});
