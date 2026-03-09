/**
 * /api/feedback routes — user feedback/suggestions endpoint.
 */

import { Router, Request, Response } from 'express';
import { supabasePost } from '../lib/supabase';

const router = Router();

/**
 * POST /api/feedback
 * Submit user feedback about a grant call or search result.
 *
 * Body:
 *  - call_id?: number (related grant call)
 *  - type: 'correction' | 'missing' | 'suggestion' | 'bug'
 *  - message: string (required, the feedback text)
 *  - contact?: string (optional email/name for follow-up)
 */
router.post('/', async (req: Request, res: Response) => {
  try {
    const { call_id, type, message, contact } = req.body;

    if (!message || typeof message !== 'string' || message.trim().length === 0) {
      res.status(400).json({ error: 'Missing or empty message' });
      return;
    }

    const validTypes = ['correction', 'missing', 'suggestion', 'bug'];
    const feedbackType = validTypes.includes(type) ? type : 'suggestion';

    // For now store in error_log with severity='feedback'
    // In Phase 2 we can add a dedicated feedback table
    const payload = {
      error_id: `FB-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      source: 'user_feedback',
      component: feedbackType,
      severity: 'info',
      message: message.trim().slice(0, 5000),
      details: JSON.stringify({
        type: feedbackType,
        call_id: call_id || null,
        contact: contact || null,
      }),
      call_id: call_id ? parseInt(String(call_id), 10) : null,
    };

    await supabasePost('error_log', [payload], 'return=minimal');

    res.status(201).json({
      status: 'ok',
      message: 'Feedback received. Thank you!',
    });
  } catch (err) {
    console.error('[POST /api/feedback]', err);
    res.status(500).json({ error: 'Failed to submit feedback', message: String(err) });
  }
});

export { router as feedbackRouter };
