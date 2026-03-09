/**
 * Supabase REST client for the backend API.
 * Uses raw fetch (no supabase-js dependency) for full control.
 */

import dotenv from 'dotenv';
import path from 'path';

// Load env from project root
dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(process.env.HOME || '', '.openclaw/.env') });

const SUPABASE_URL = process.env.SUPABASE_URL || '';
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || '';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY || '';

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY');
}

function headers(prefer = 'return=representation'): Record<string, string> {
  return {
    apikey: SUPABASE_KEY,
    Authorization: `Bearer ${SUPABASE_KEY}`,
    'Content-Type': 'application/json',
    Prefer: prefer,
  };
}

export async function supabaseGet<T = unknown>(
  table: string,
  params: Record<string, string> = {},
  options: { count?: boolean } = {}
): Promise<{ data: T[]; count?: number }> {
  const url = new URL(`${SUPABASE_URL}/rest/v1/${table}`);
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }

  const h = headers();
  if (options.count) {
    h.Prefer = 'count=exact';
  }

  const resp = await fetch(url.toString(), { headers: h });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Supabase GET ${table} failed (${resp.status}): ${body}`);
  }

  const data = (await resp.json()) as T[];
  let count: number | undefined;
  if (options.count) {
    const range = resp.headers.get('content-range');
    if (range) {
      const total = range.split('/')[1];
      count = total === '*' ? undefined : parseInt(total, 10);
    }
  }

  return { data, count };
}

export async function supabasePost<T = unknown>(
  table: string,
  body: unknown,
  prefer = 'return=representation'
): Promise<T[]> {
  const url = `${SUPABASE_URL}/rest/v1/${table}`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: headers(prefer),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Supabase POST ${table} failed (${resp.status}): ${text}`);
  }
  const text = await resp.text();
  return text ? JSON.parse(text) : [];
}

export async function supabaseRpc<T = unknown>(
  fnName: string,
  params: Record<string, unknown>
): Promise<T> {
  const url = `${SUPABASE_URL}/rest/v1/rpc/${fnName}`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Supabase RPC ${fnName} failed (${resp.status}): ${text}`);
  }
  const text = await resp.text();
  return text ? JSON.parse(text) : (null as T);
}

export { SUPABASE_URL, SUPABASE_KEY, SUPABASE_ANON_KEY };
