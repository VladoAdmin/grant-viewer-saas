/**
 * Search service — hybrid search with RRF via Supabase RPC.
 */

import { supabaseRpc, supabaseGet } from '../lib/supabase';
import { embedQuery } from '../lib/openai';

export interface SearchParams {
  query: string;
  callId?: number;
  docType?: string;
  limit: number;
}

export interface SearchResult {
  id: number;
  call_id: number;
  call_title: string;
  chunk_content: string;
  source: string;
  doc_type: string;
  similarity: number;
  rank: number;
}

/**
 * Run hybrid search: embed query, call RPC, enrich with call titles.
 */
export async function hybridSearch(params: SearchParams): Promise<SearchResult[]> {
  // 1. Embed the query
  const queryEmbedding = await embedQuery(params.query);

  // 2. Call Supabase RPC
  // Always pass all params (including null) to resolve PostgREST overload ambiguity
  const rpcParams: Record<string, unknown> = {
    query_text: params.query,
    query_embedding: JSON.stringify(queryEmbedding),
    match_threshold: 0.3,
    match_count: params.limit,
    call_id_filter: params.callId ?? null,
    doc_type_filter: params.docType ?? null,
  };

  const rawResults = await supabaseRpc<Array<Record<string, unknown>>>(
    'hybrid_search_chunks',
    rpcParams
  );

  if (!rawResults || !Array.isArray(rawResults) || rawResults.length === 0) {
    return [];
  }

  // 3. Get unique call IDs and fetch titles
  const callIds = [...new Set(rawResults.map((r) => r.call_id as number))];
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

  // 4. Map results
  return rawResults.map((r) => ({
    id: r.id as number,
    call_id: r.call_id as number,
    call_title: titleMap[r.call_id as number] || 'Unknown',
    chunk_content: r.chunk_content as string,
    source: (r.source as string) || '',
    doc_type: (r.doc_type as string) || '',
    similarity: r.similarity as number,
    rank: r.rank as number,
  }));
}
