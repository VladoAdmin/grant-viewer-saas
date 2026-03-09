/**
 * OpenAI client for embedding queries (search).
 */

import OpenAI from 'openai';
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(process.env.HOME || '', '.openclaw/.env') });

const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';

if (!OPENAI_API_KEY) {
  console.error('Missing OPENAI_API_KEY');
}

const openai = new OpenAI({ apiKey: OPENAI_API_KEY });

/** Embed model must match what's stored in DB (text-embedding-3-large, 3072 dim). */
const EMBED_MODEL = 'text-embedding-3-large';

export async function embedQuery(text: string): Promise<number[]> {
  const resp = await openai.embeddings.create({
    model: EMBED_MODEL,
    input: text,
  });
  return resp.data[0].embedding;
}

export { openai, EMBED_MODEL };
