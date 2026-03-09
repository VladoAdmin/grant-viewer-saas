-- SQL to create match_call_chunks RPC function for semantic search
-- Run this in Supabase SQL Editor

-- Enable pgvector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing function if it exists
DROP FUNCTION IF EXISTS match_call_chunks(vector(1536), float, int);

-- Create the match_call_chunks function
CREATE OR REPLACE FUNCTION match_call_chunks(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.5,
  match_count int DEFAULT 10
)
RETURNS TABLE(
  id uuid,
  call_id text,
  chunk_text text,
  chunk_index int,
  token_count int,
  source_type text,
  source_url text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    v2_call_chunks.id,
    v2_call_chunks.call_id,
    v2_call_chunks.chunk_text,
    v2_call_chunks.chunk_index,
    v2_call_chunks.token_count,
    v2_call_chunks.source_type,
    v2_call_chunks.source_url,
    1 - (v2_call_chunks.embedding <=> query_embedding) AS similarity
  FROM v2_call_chunks
  WHERE 1 - (v2_call_chunks.embedding <=> query_embedding) > match_threshold
  ORDER BY v2_call_chunks.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Grant execute permission to all users (or specific roles)
GRANT EXECUTE ON FUNCTION match_call_chunks(vector(1536), float, int) TO PUBLIC;

-- Create index on embedding column if not exists (for faster similarity search)
CREATE INDEX IF NOT EXISTS idx_v2_call_chunks_embedding 
ON v2_call_chunks 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Verify function was created
SELECT 
  proname AS function_name,
  pg_get_function_arguments(oid) AS arguments,
  pg_get_function_result(oid) AS return_type
FROM pg_proc 
WHERE proname = 'match_call_chunks';
