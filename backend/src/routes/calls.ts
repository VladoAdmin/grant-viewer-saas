/**
 * /api/calls routes — list + detail + PDF export.
 */

import { Router, Request, Response } from 'express';
import { supabaseGet } from '../lib/supabase';
import { getCallDetail } from '../services/callService';
import { generatePdf } from '../services/pdfService';
import { extractCallAttributes } from '../services/extractionService';

const router = Router();

/**
 * GET /api/calls
 * List grant calls with optional filters and pagination.
 *
 * Query params:
 *  - source: filter by source (e.g. portal.itms21.sk)
 *  - status: filter by status
 *  - deadline_after: ISO date, calls with deadline >= this
 *  - deadline_before: ISO date, calls with deadline <= this
 *  - page: page number (default 1)
 *  - limit: items per page (default 20, max 100)
 *  - search: basic title text search
 */
router.get('/', async (req: Request, res: Response) => {
  try {
    const {
      source,
      status,
      deadline_after,
      deadline_before,
      page: pageStr,
      limit: limitStr,
      search,
    } = req.query;

    const page = Math.max(1, parseInt(pageStr as string, 10) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(limitStr as string, 10) || 20));
    const offset = (page - 1) * limit;

    const params: Record<string, string> = {
      select: '*',
      order: 'deadline_at.asc.nullslast,created_at.desc',
      limit: String(limit),
      offset: String(offset),
      deleted_at: 'is.null',
    };

    if (source) params.source = `eq.${source}`;
    if (status) params.status = `ilike.*${status}*`;
    if (deadline_after) params['deadline_at'] = `gte.${deadline_after}`;
    if (deadline_before) {
      // If deadline_after is also set, use AND logic via PostgREST
      if (deadline_after) {
        params['and'] = `(deadline_at.gte.${deadline_after},deadline_at.lte.${deadline_before})`;
        delete params['deadline_at'];
      } else {
        params['deadline_at'] = `lte.${deadline_before}`;
      }
    }
    if (search) params.title = `ilike.*${search}*`;

    const { data, count } = await supabaseGet('grant_calls_v2', params, { count: true });

    res.json({
      data,
      total: count ?? data.length,
      page,
      limit,
    });
  } catch (err) {
    console.error('[GET /api/calls]', err);
    res.status(500).json({ error: 'Failed to fetch calls', message: String(err) });
  }
});

/**
 * GET /api/calls/:id
 * Get call detail with attributes and attachments.
 */
router.get('/:id', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) {
      res.status(400).json({ error: 'Invalid call ID' });
      return;
    }

    const detail = await getCallDetail(id);
    if (!detail) {
      res.status(404).json({ error: 'Call not found' });
      return;
    }

    res.json(detail);
  } catch (err) {
    console.error('[GET /api/calls/:id]', err);
    res.status(500).json({ error: 'Failed to fetch call detail', message: String(err) });
  }
});

/**
 * GET /api/calls/:id/extracted-attributes
 * Extract structured attributes from PDF chunks via vector search + GPT.
 * Results are cached in grant_call_attributes with vs_ prefix.
 */
router.get('/:id/extracted-attributes', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) {
      res.status(400).json({ error: 'Invalid call ID' });
      return;
    }

    const attributes = await extractCallAttributes(id);
    res.json(attributes);
  } catch (err) {
    console.error('[GET /api/calls/:id/extracted-attributes]', err);
    res.status(500).json({
      error: 'Failed to extract attributes',
      message: String(err),
    });
  }
});

/**
 * GET /api/calls/:id/export-pdf
 * Generate and download a PDF summary for a grant call.
 */
router.get('/:id/export-pdf', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) {
      res.status(400).json({ error: 'Invalid call ID' });
      return;
    }

    const detail = await getCallDetail(id);
    if (!detail) {
      res.status(404).json({ error: 'Call not found' });
      return;
    }

    const pdfBuffer = await generatePdf(detail);

    const filename = `grant-call-${id}.pdf`;
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    res.send(pdfBuffer);
  } catch (err) {
    console.error('[GET /api/calls/:id/export-pdf]', err);
    res.status(500).json({ error: 'Failed to generate PDF', message: String(err) });
  }
});

export { router as callsRouter };
