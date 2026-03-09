/**
 * Grant Viewer SaaS — Express.js API server.
 */

import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

// Load env
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(process.env.HOME || '', '.openclaw/.env') });

import { callsRouter } from './routes/calls';
import { searchRouter } from './routes/search';
import { adminRouter } from './routes/admin';
import { feedbackRouter } from './routes/feedback';

const app = express();
const PORT = parseInt(process.env.PORT || '3001', 10);

// Middleware
// Handle Private Network Access (PNA) preflight — Chrome requires this
// for cross-origin requests to local/private network addresses
app.use((_req, _res, next) => {
  _res.setHeader('Access-Control-Allow-Private-Network', 'true');
  next();
});
app.use(cors({
  origin: process.env.CORS_ORIGIN || '*',
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'Access-Control-Request-Private-Network'],
}));
app.use(express.json({ limit: '1mb' }));

// Health endpoint
app.get('/api/health', (_req: Request, res: Response) => {
  res.json({
    status: 'ok',
    service: 'grant-viewer-api',
    timestamp: new Date().toISOString(),
  });
});

// Routes
app.use('/api/calls', callsRouter);
app.use('/api/search', searchRouter);
app.use('/api/admin', adminRouter);
app.use('/api/feedback', feedbackRouter);

// Serve frontend static files in production
const frontendPath = path.resolve(__dirname, '../../frontend/dist');
if (fs.existsSync(frontendPath)) {
  app.use(express.static(frontendPath));
  // SPA fallback: serve index.html for non-API routes
  app.get('*', (req: Request, res: Response, next: NextFunction) => {
    if (req.path.startsWith('/api/')) {
      next();
      return;
    }
    res.sendFile(path.join(frontendPath, 'index.html'));
  });
}

// 404 handler (for API routes)
app.use((_req: Request, res: Response) => {
  res.status(404).json({ error: 'Not found', message: 'Endpoint does not exist' });
});

// Global error handler
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  console.error('[API Error]', err.message);
  res.status(500).json({
    error: 'Internal server error',
    message: process.env.NODE_ENV === 'production' ? 'Something went wrong' : err.message,
  });
});

// Start server (only when not imported for testing)
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Grant Viewer API running on http://localhost:${PORT}`);
  });
}

export { app };
