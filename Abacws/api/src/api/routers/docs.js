const express = require("express");
const swaggerUi = require("swagger-ui-express");
const { readFileSync } = require("fs");
const { parse } = require("yaml");

const file = readFileSync("openapi.yaml", "utf-8");
const openapi = parse(file);

const router = express.Router();

router.all("/openapi.json", (_req, res) => {
  res.status(200).json(openapi);
});
router.use("/", swaggerUi.serve, swaggerUi.setup(openapi));

module.exports = router;
