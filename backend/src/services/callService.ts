/**
 * Call service — business logic for grant call operations.
 */

import { supabaseGet } from '../lib/supabase';

export interface CallDetail {
  call: Record<string, unknown>;
  attributes: Record<string, string>;
  attachments: Array<Record<string, unknown>>;
}

/**
 * Get full call detail with attributes and attachments.
 */
export async function getCallDetail(id: number): Promise<CallDetail | null> {
  // Fetch call
  const { data: calls } = await supabaseGet('grant_calls_v2', {
    id: `eq.${id}`,
    limit: '1',
  });

  if (calls.length === 0) return null;

  const call = calls[0] as Record<string, unknown>;

  // Fetch attributes
  const { data: attrRows } = await supabaseGet<Record<string, unknown>>('grant_call_attributes', {
    grant_call_id: `eq.${id}`,
    select: 'key,value,value_type',
  });

  const attributes: Record<string, string> = {};
  for (const row of attrRows) {
    attributes[row.key as string] = row.value as string;
  }

  // Fetch attachments
  const { data: attachments } = await supabaseGet<Record<string, unknown>>('grant_call_attachments', {
    grant_call_id: `eq.${id}`,
    select: '*',
  });

  return { call, attributes, attachments };
}
