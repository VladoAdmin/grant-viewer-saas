/**
 * /api/search routes — hybrid search endpoint.
 * Supports deep=true for reranked + completeness-evaluated results via Python micro-API.
 */

import { Router, Request, Response } from 'express';
import { hybridSearch } from '../services/searchService';

const router = Router();

const PYTHON_SEARCH_API = process.env.PYTHON_SEARCH_API || 'http://localhost:3002';

/**
 * POST /api/search
 * Hybrid search (vector + fulltext + RRF).
 *
 * Body:
 *  - query: string (required)
 *  - call_id?: number (filter to specific call)
 *  - doc_type?: string (filter by document type)
 *  - limit?: number (default 10, max 50)
 *  - deep?: boolean (default false — when true, uses Python reranker + completeness)
 */
router.post('/', async (req: Request, res: Response) => {
  try {
    const { query, call_id, doc_type, limit: limitParam, deep } = req.body;

    if (!query || typeof query !== 'string' || query.trim().length === 0) {
      res.status(400).json({ error: 'Missing or empty query' });
      return;
    }

    const limit = Math.min(50, Math.max(1, parseInt(limitParam, 10) || 10));
    const start = Date.now();

    // Deep search: delegate to Python micro-API
    if (deep) {
      try {
        const pyResp = await fetch(`${PYTHON_SEARCH_API}/search-deep`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query.trim(),
            call_id: call_id ? parseInt(call_id, 10) : null,
            limit,
          }),
        });

        if (!pyResp.ok) {
          const errBody = (await pyResp.json().catch(() => ({}))) as Record<string, unknown>;
          throw new Error((errBody.error as string) || `Python API returned ${pyResp.status}`);
        }

        const pyData = (await pyResp.json()) as {
          results: Array<Record<string, unknown>>;
          completeness?: Record<string, unknown>;
          took_ms?: number;
          total?: number;
          query?: string;
        };

        // Enrich with call titles if missing
        if (pyData.results && pyData.results.length > 0) {
          const { supabaseGet } = await import('../lib/supabase');
          const callIds = [...new Set(pyData.results.map((r) => r.call_id as number).filter(Boolean))];
          const titleMap: Record<number, string> = {};

          if (callIds.length > 0) {
            const idFilter = `in.(${callIds.join(',')})`;
            const { data: calls } = await supabaseGet<Record<string, unknown>>('grant_calls_v2', {
              id: idFilter,
              select: 'id,title',
            });
            for (const c of calls) {
              titleMap[c.id as number] = c.title as string;
            }
          }

          for (const r of pyData.results) {
            r.call_title = titleMap[r.call_id as number] || (r.call_title as string) || 'Unknown';
          }
        }

        res.json({
          results: pyData.results,
          completeness: pyData.completeness,
          query: pyData.query,
          total: pyData.total,
          deep: true,
          took_ms: Date.now() - start,
        });
        return;
      } catch (pyErr) {
        console.error('[POST /api/search] Deep search failed, falling back to basic:', pyErr);
        // Fall through to basic search
      }
    }

    // Basic search (default)
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
      deep: false,
    });
  } catch (err) {
    console.error('[POST /api/search]', err);
    res.status(500).json({ error: 'Search failed', message: String(err) });
  }
});

export { router as searchRouter };
