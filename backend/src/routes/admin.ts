/**
 * /api/admin routes — status + trigger.
 */

import { Router, Request, Response } from 'express';
import { exec } from 'child_process';
import path from 'path';
import { supabaseGet } from '../lib/supabase';

const router = Router();

/**
 * GET /api/admin/status
 * Get scraper status: last runs per source + overall stats.
 */
router.get('/status', async (_req: Request, res: Response) => {
  try {
    // Last runs
    const { data: runs } = await supabaseGet('scraper_runs', {
      select: '*',
      order: 'started_at.desc',
      limit: '20',
    });

    // Group by source — get latest per source
    const bySource: Record<string, unknown> = {};
    for (const run of runs) {
      const src = (run as Record<string, unknown>).source as string;
      if (!bySource[src]) {
        bySource[src] = run;
      }
    }

    // Get overall stats
    const { data: callStats, count: totalCalls } = await supabaseGet('grant_calls_v2', {
      select: 'id',
      deleted_at: 'is.null',
    }, { count: true });

    const { data: chunkStats, count: totalChunks } = await supabaseGet('v2_call_chunks', {
      select: 'id',
      deleted_at: 'is.null',
    }, { count: true });

    res.json({
      sources: bySource,
      recent_runs: runs.slice(0, 10),
      stats: {
        total_calls: totalCalls ?? callStats.length,
        total_chunks: totalChunks ?? chunkStats.length,
      },
    });
  } catch (err) {
    console.error('[GET /api/admin/status]', err);
    res.status(500).json({ error: 'Failed to fetch status', message: String(err) });
  }
});

/**
 * POST /api/admin/trigger
 * Trigger a scraper run.
 *
 * Body: { source: "itms21" | "all" }
 */
router.post('/trigger', async (req: Request, res: Response) => {
  try {
    const { source } = req.body;
    if (!source || !['itms21', 'all'].includes(source)) {
      res.status(400).json({
        error: 'Invalid source',
        message: 'Must be one of: itms21, all',
      });
      return;
    }

    const scraperDir = path.resolve(__dirname, '../../../scraper');
    const cmd = `cd "${scraperDir}" && python3 main.py scrape --source ${source}`;

    // Spawn async — don't wait for completion
    const child = exec(cmd, { timeout: 600000 });

    child.stdout?.on('data', (d: string) => console.log('[scraper]', d.trim()));
    child.stderr?.on('data', (d: string) => console.error('[scraper]', d.trim()));
    child.on('exit', (code: number | null) => {
      console.log(`[scraper] Process exited with code ${code}`);
    });

    res.json({
      status: 'triggered',
      source,
      message: `Scraper started for source: ${source}`,
    });
  } catch (err) {
    console.error('[POST /api/admin/trigger]', err);
    res.status(500).json({ error: 'Failed to trigger scraper', message: String(err) });
  }
});

export { router as adminRouter };
