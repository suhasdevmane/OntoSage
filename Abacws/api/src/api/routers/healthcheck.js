const express = require("express");
const client = require("../database");

const router = express.Router();

router.all("/", async (req, res, next) => {
  try {
    const dbStatus = await client.db().command({ ping: 1 });
    if (dbStatus?.ok) {
      return res.status(200).json({ health: "OK" });
    }
    return res.status(500).json({ health: "FAIL" });
  } catch (e) {
    return res.status(500).json({ health: "FAIL" });
  }
});

module.exports = router;
