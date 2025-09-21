import express, { Request, Response } from "express";
import api from "./api";
import { PORT, URL_PREFIX } from './api/constants';

const app = express()

// Simple process health endpoint (does not depend on DB)
app.get('/health', (_req: Request, res: Response) => {
    res.status(200).json({ status: 'ok' });
});

app.use(URL_PREFIX, api);

// Start api
app.listen(PORT, () => {
    console.log(`API is listening on '${PORT}'...`)
});
