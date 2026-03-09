/**
 * Vector Search Attribute Extraction Service
 * 
 * Uses hybrid_search_chunks_v2 RPC + GPT-4o-mini to extract
 * structured attributes from PDF chunks for a given call.
 */

import OpenAI from 'openai';
import { supabaseRpc, supabaseGet, supabasePost } from '../lib/supabase';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const EMBEDDING_MODEL = 'text-embedding-3-large'; // 3072 dim — must match DB vectors
const EXTRACTION_MODEL = 'gpt-4o-mini';

const EXTRACTION_FIELDS = [
  'Kód výzvy',
  'Program',
  'Špecifický cieľ',
  'Opatrenie',
  'Fond',
  'Oprávnení žiadatelia',
  'Miesto realizácie',
  'Alokácia EÚ',
  'Alokácia ŠR',
  'Alokácia spolu',
  'Oprávnené aktivity',
  'Oprávnené výdavky',
  'Posudzované obdobia',
  'Kontakt',
];

const SEARCH_QUERIES = [
  'kód výzvy, program, priorita, špecifický cieľ, opatrenie, fond',
  'celková alokácia finančné prostriedky EÚ ŠR suma eurá oprávnené výdavky',
  'oprávnení žiadatelia miesto realizácie posudzované obdobia dátum uzávierky oprávnené aktivity',
];

interface ChunkResult {
  id: number;
  call_id: number;
  chunk_content: string;
  source: string;
  doc_type: string;
  chunk_metadata: Record<string, unknown>;
  similarity: number;
  rank: number;
}

interface ExtractedAttributes {
  [key: string]: string;
}

/**
 * Generate embedding for a text query using text-embedding-3-large (3072 dim).
 */
async function getEmbedding(text: string): Promise<number[]> {
  const response = await openai.embeddings.create({
    model: EMBEDDING_MODEL,
    input: text,
  });
  return response.data[0].embedding;
}

/**
 * Run a single hybrid search query against v2_call_chunks.
 */
async function searchChunks(
  queryText: string,
  queryEmbedding: number[],
  callId: number,
  matchCount: number = 8
): Promise<ChunkResult[]> {
  return supabaseRpc<ChunkResult[]>('hybrid_search_chunks_v2', {
    query_text: queryText,
    query_embedding: queryEmbedding,
    match_count: matchCount,
    match_threshold: 0.2,
    call_id_filter: callId,
    doc_type_filter: null,
  });
}

/**
 * Deduplicate chunks by id, keeping the highest-ranked version.
 */
function deduplicateChunks(allChunks: ChunkResult[]): ChunkResult[] {
  const seen = new Map<number, ChunkResult>();
  for (const chunk of allChunks) {
    if (!seen.has(chunk.id)) {
      seen.set(chunk.id, chunk);
    }
  }
  // Sort by rank ascending (lower rank = more relevant)
  return Array.from(seen.values())
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 15);
}

/**
 * Extract structured attributes from chunks using GPT-4o-mini.
 */
async function extractWithGPT(chunks: ChunkResult[]): Promise<ExtractedAttributes> {
  const chunksText = chunks
    .map((c, i) => `--- Úryvok ${i + 1} ---\n${c.chunk_content}`)
    .join('\n\n');

  const fieldsList = EXTRACTION_FIELDS.map(f => `- ${f}`).join('\n');

  const systemPrompt = `Si asistent pre extrakciu štruktúrovaných údajov z grantových výziev.
Na základe poskytnutých textových úryvkov extrahuj tieto údaje:
${fieldsList}

Pravidlá:
- Ak údaj nie je v texte, vráť "—"
- Sumy formátuj ako "X,XXX,XXX.XX €"
- Miesto realizácie: vypíš všetky kraje/okresy
- Oprávnení žiadatelia: vypíš všetky typy
- Odpovedaj VÝHRADNE ako JSON objekt s presne týmito kľúčmi`;

  const response = await openai.chat.completions.create({
    model: EXTRACTION_MODEL,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: chunksText },
    ],
    response_format: { type: 'json_object' },
    temperature: 0,
    max_tokens: 2000,
  });

  const content = response.choices[0]?.message?.content || '{}';
  try {
    return JSON.parse(content) as ExtractedAttributes;
  } catch {
    console.error('[extractWithGPT] Failed to parse response:', content);
    return {};
  }
}

/**
 * Check cache for previously extracted attributes.
 */
async function getCachedAttributes(callId: number): Promise<ExtractedAttributes | null> {
  try {
    const { data } = await supabaseGet<{
      id: number;
      grant_call_id: number;
      key: string;
      value: string;
    }>('grant_call_attributes', {
      grant_call_id: `eq.${callId}`,
      key: 'like.vs_%',
      select: 'id,grant_call_id,key,value',
    });

    if (!data || data.length === 0) return null;

    const result: ExtractedAttributes = {};
    for (const row of data) {
      // Strip vs_ prefix to get the original field name
      const fieldName = row.key.replace(/^vs_/, '');
      result[fieldName] = row.value;
    }
    return result;
  } catch (err) {
    console.warn('[getCachedAttributes] Cache check failed:', err);
    return null;
  }
}

/**
 * Store extracted attributes in cache with vs_ prefix.
 */
async function cacheAttributes(callId: number, attributes: ExtractedAttributes): Promise<void> {
  try {
    // Delete old vs_ attributes for this call first
    const deleteUrl = `${process.env.SUPABASE_URL}/rest/v1/grant_call_attributes?grant_call_id=eq.${callId}&key=like.vs_%`;
    await fetch(deleteUrl, {
      method: 'DELETE',
      headers: {
        apikey: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
        Authorization: `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY || ''}`,
        'Content-Type': 'application/json',
      },
    });

    // Insert new attributes
    const rows = Object.entries(attributes)
      .filter(([_, v]) => v && v !== '—')
      .map(([key, value]) => ({
        grant_call_id: callId,
        key: `vs_${key}`,
        value,
        value_type: 'text',
        extracted_at: new Date().toISOString(),
      }));

    if (rows.length > 0) {
      await supabasePost('grant_call_attributes', rows);
    }
  } catch (err) {
    console.error('[cacheAttributes] Failed to cache:', err);
    // Non-fatal — extraction still returns data
  }
}

/**
 * Main extraction function: check cache, or run vector search + GPT extraction.
 */
export async function extractCallAttributes(callId: number): Promise<ExtractedAttributes> {
  // 1. Check cache
  const cached = await getCachedAttributes(callId);
  if (cached && Object.keys(cached).length > 0) {
    console.log(`[extractCallAttributes] Cache hit for call_id=${callId}`);
    return cached;
  }

  console.log(`[extractCallAttributes] Cache miss for call_id=${callId}, running extraction...`);

  // 2. Run 3 parallel vector search queries
  const embeddings = await Promise.all(
    SEARCH_QUERIES.map(q => getEmbedding(q))
  );

  const searchResults = await Promise.all(
    SEARCH_QUERIES.map((q, i) => searchChunks(q, embeddings[i], callId))
  );

  // 3. Flatten and deduplicate
  const allChunks = searchResults.flat();
  if (allChunks.length === 0) {
    console.warn(`[extractCallAttributes] No chunks found for call_id=${callId}`);
    return {};
  }

  const uniqueChunks = deduplicateChunks(allChunks);
  console.log(`[extractCallAttributes] Got ${uniqueChunks.length} unique chunks from ${allChunks.length} total`);

  // 4. Extract with GPT
  const attributes = await extractWithGPT(uniqueChunks);

  // 5. Cache results
  await cacheAttributes(callId, attributes);

  return attributes;
}
