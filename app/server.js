'use strict';
/**
 * Loan EMI Calculator - Express + MongoDB
 * All configuration comes from environment variables (no hard-coded hosts/passwords).
 */
const express = require('express');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { MongoClient } = require('mongodb');

const MONGO_URL = process.env.MONGO_URL;
if (!MONGO_URL) {
  console.error('FATAL: MONGO_URL environment variable is not set');
  process.exit(1);
}
const PORT = parseInt(process.env.PORT || '3000', 10);
const VERSION = process.env.APP_VERSION || '1.0';
const POD_NAME = process.env.HOSTNAME || os.hostname();   // Kubernetes sets HOSTNAME = pod name

function findPodIP() {
  if (process.env.POD_IP) return process.env.POD_IP;      // injected with the downward API
  for (const list of Object.values(os.networkInterfaces())) {
    for (const a of list || []) if (a.family === 'IPv4' && !a.internal) return a.address;
  }
  return '127.0.0.1';
}
const POD_IP = findPodIP();

// ---------- MongoDB connection (retries until the replica set is ready) ----------
let client = null;
let calculations = null;

async function connectWithRetry() {
  for (;;) {
    const c = new MongoClient(MONGO_URL, { serverSelectionTimeoutMS: 5000, maxPoolSize: 50 });
    try {
      await c.connect();
      await c.db('admin').command({ ping: 1 });
      client = c;
      calculations = c.db().collection('calculations');      // db name comes from MONGO_URL (emidb)
      calculations.createIndex({ createdAt: -1 }).catch(() => {});
      console.log(`[${POD_NAME}] connected to MongoDB`);
      return;
    } catch (err) {
      console.error(`[${POD_NAME}] MongoDB not reachable yet (${err.message}); retrying in 3s`);
      try { await c.close(); } catch (_) { /* ignore */ }
      await new Promise(r => setTimeout(r, 3000));
    }
  }
}
connectWithRetry();

// ---------- helpers ----------
const round2 = x => Math.round(x * 100) / 100;

function parseInputs(body) {
  const P = Number(body.P ?? body.principal);
  const rate = Number(body.rate);
  const n = Number(body.n ?? body.months);
  const errors = [];
  if (!Number.isFinite(P) || P <= 0) errors.push('Loan amount must be a positive number.');
  if (!Number.isFinite(rate) || rate <= 0 || rate > 100) errors.push('Annual interest rate must be a positive number up to 100.');
  if (!Number.isInteger(n) || n <= 0 || n > 600) errors.push('Tenure must be a positive whole number of months (up to 600).');
  return { P, rate, n, errors };
}

function calculateEmi(P, annualRate, n) {
  const r = annualRate / 12 / 100;
  const f = Math.pow(1 + r, n);
  return (P * r * f) / (f - 1);
}

// ---------- app ----------
const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '10kb' }));
app.use(express.urlencoded({ extended: false, limit: '10kb' }));

const indexHtml = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8')
  .replace(/\{\{VERSION\}\}/g, VERSION);
app.get('/', (req, res) => res.type('html').send(indexHtml));
app.use(express.static(path.join(__dirname, 'public'), { index: false }));

app.post('/api/emi', async (req, res) => {
  const { P, rate, n, errors } = parseInputs(req.body || {});
  if (errors.length) return res.status(400).json({ errors, servedBy: POD_NAME, podIP: POD_IP });

  const emi = round2(calculateEmi(P, rate, n));
  const totalPayment = round2(emi * n);
  const result = {
    principal: P, rate, months: n, emi, totalPayment,
    totalInterest: round2(totalPayment - P),
    servedBy: POD_NAME, podIP: POD_IP, version: VERSION,
  };
  if (!calculations) return res.status(503).json({ error: 'Database is not connected yet', servedBy: POD_NAME, podIP: POD_IP });
  try {
    await calculations.insertOne({ principal: P, rate, months: n, emi, servedBy: POD_NAME, createdAt: new Date() });
    res.json(result);
  } catch (err) {
    console.error('insert failed:', err.message);
    res.status(503).json({ error: 'Could not save the calculation: ' + err.message, servedBy: POD_NAME, podIP: POD_IP });
  }
});

app.get('/api/history', async (req, res) => {
  if (!calculations) return res.status(503).json({ error: 'Database is not connected yet' });
  try {
    const docs = await calculations.find({}, { projection: { _id: 0 } })
      .sort({ createdAt: -1 }).limit(10).toArray();
    res.json(docs);
  } catch (err) {
    res.status(503).json({ error: err.message });
  }
});

app.get('/api/info', (req, res) => res.json({ version: VERSION, servedBy: POD_NAME, podIP: POD_IP }));

// 200 only when MongoDB is reachable (used by readiness + liveness probes)
app.get('/health', async (req, res) => {
  if (!client) return res.status(503).json({ status: 'connecting', servedBy: POD_NAME });
  try {
    await Promise.race([
      client.db('admin').command({ ping: 1 }, { readPreference: 'primaryPreferred' }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('ping timeout')), 2000)),
    ]);
    res.json({ status: 'ok', servedBy: POD_NAME });
  } catch (err) {
    res.status(503).json({ status: 'mongo-unreachable', error: err.message, servedBy: POD_NAME });
  }
});

const server = app.listen(PORT, () => console.log(`[${POD_NAME}] emi-web v${VERSION} listening on :${PORT}`));
// Keep-alive longer than the NGINX upstream keep-alive so NGINX never reuses a socket we closed
server.keepAliveTimeout = 65000;
server.headersTimeout = 66000;

function shutdown(sig) {
  console.log(`[${POD_NAME}] ${sig} received, shutting down gracefully`);
  server.close(() => {
    Promise.resolve(client && client.close()).finally(() => process.exit(0));
  });
  if (server.closeIdleConnections) server.closeIdleConnections();
  setTimeout(() => process.exit(0), 20000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
