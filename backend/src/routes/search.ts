/**
 * /api/search routes — hybrid search endpoint.
 */

import { Router, Request, Response } from 'express';
import { hybridSearch } from '../services/searchService';

const router = Router();

/**
 * POST /api/search
 * Hybrid search (vector + fulltext + RRF).
 *
 * Body:
 *  - query: string (required)
 *  - call_id?: number (filter to specific call)
 *  - doc_type?: string (filter by document type)
 *  - limit?: number (default 10, max 50)
 */
router.post('/', async (req: Request, res: Response) => {
  try {
    const { query, call_id, doc_type, limit: limitParam } = req.body;

    if (!query || typeof query !== 'string' || query.trim().length === 0) {
      res.status(400).json({ error: 'Missing or empty query' });
      return;
    }

    const limit = Math.min(50, Math.max(1, parseInt(limitParam, 10) || 10));
    const start = Date.now();

    const results = await hybridSearch({
      query: query.trim(),
      callId: call_id ? parseInt(call_id, 10) : undefined,
      docType: doc_type,
      limit,
    });

    res.json({
      results,
      query: query.trim(),
      took_ms: Date.now() - start,
      total: results.length,
    });
  } catch (err) {
    console.error('[POST /api/search]', err);
    res.status(500).json({ error: 'Search failed', message: String(err) });
  }
});

export { router as searchRouter };
