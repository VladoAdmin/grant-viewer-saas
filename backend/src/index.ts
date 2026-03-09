/**
 * Grant Viewer SaaS — Express.js API server.
 */

import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';

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
app.use(cors({
  origin: process.env.CORS_ORIGIN || '*',
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
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

// 404 handler
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
