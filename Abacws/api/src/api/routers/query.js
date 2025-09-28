const express = require("express");
const queryMiddleware = require("../middleware/query");

const router = express.Router();

router.get('/', queryMiddleware, async (req, res) => {
  res.status(200).json(res.locals.devices || []);
});

module.exports = router;
