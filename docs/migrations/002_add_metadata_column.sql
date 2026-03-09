-- TASK-002: Add metadata JSONB column to v2_call_chunks
-- Run: psql -h $SUPABASE_HOST -U $SUPABASE_USER -d postgres -f docs/migrations/002_add_metadata_column.sql

ALTER TABLE v2_call_chunks ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Updated hybrid search that also returns metadata
CREATE OR REPLACE FUNCTION public.hybrid_search_chunks_v2(
    query_text text,
    query_embedding vector,
    match_threshold double precision DEFAULT 0.3,
    match_count integer DEFAULT 10,
    call_id_filter integer DEFAULT NULL::integer,
    doc_type_filter text DEFAULT NULL::text
)
RETURNS TABLE(
    id integer,
    call_id integer,
    chunk_content text,
    source text,
    doc_type text,
    chunk_metadata jsonb,
    similarity double precision,
    rank integer
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            c.id::INT,
            c.call_id::INT,
            c.content AS chunk_content,
            c.source,
            c.doc_type,
            c.metadata AS chunk_metadata,
            (1 - (c.embedding <=> query_embedding))::FLOAT AS similarity,
            ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS vector_rank
        FROM v2_call_chunks c
        WHERE c.deleted_at IS NULL
          AND (call_id_filter IS NULL OR c.call_id = call_id_filter)
          AND (doc_type_filter IS NULL OR c.doc_type = doc_type_filter)
          AND (1 - (c.embedding <=> query_embedding)) > match_threshold
        ORDER BY c.embedding <=> query_embedding
        LIMIT match_count * 3
    ),
    text_results AS (
        SELECT
            c.id::INT,
            c.call_id::INT,
            c.content AS chunk_content,
            c.source,
            c.doc_type,
            c.metadata AS chunk_metadata,
            ts_rank(
                to_tsvector('simple', c.content),
                plainto_tsquery('simple', query_text)
            )::FLOAT AS similarity,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank(
                    to_tsvector('simple', c.content),
                    plainto_tsquery('simple', query_text)
                ) DESC
            ) AS text_rank
        FROM v2_call_chunks c
        WHERE c.deleted_at IS NULL
          AND (call_id_filter IS NULL OR c.call_id = call_id_filter)
          AND (doc_type_filter IS NULL OR c.doc_type = doc_type_filter)
          AND to_tsvector('simple', c.content) @@ plainto_tsquery('simple', query_text)
        ORDER BY similarity DESC
        LIMIT match_count * 3
    ),
    combined AS (
        SELECT
            COALESCE(v.id, t.id) AS id,
            COALESCE(v.call_id, t.call_id) AS call_id,
            COALESCE(v.chunk_content, t.chunk_content) AS chunk_content,
            COALESCE(v.source, t.source) AS source,
            COALESCE(v.doc_type, t.doc_type) AS doc_type,
            COALESCE(v.chunk_metadata, t.chunk_metadata) AS chunk_metadata,
            (COALESCE(v.similarity, 0) + COALESCE(t.similarity, 0) * 0.5)::FLOAT AS combined_score,
            (COALESCE(1.0 / (60 + v.vector_rank), 0) + COALESCE(1.0 / (60 + t.text_rank), 0))::FLOAT AS rrf_score
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.id = t.id
    )
    SELECT
        co.id,
        co.call_id,
        co.chunk_content,
        co.source,
        co.doc_type,
        co.chunk_metadata,
        co.combined_score AS similarity,
        ROW_NUMBER() OVER (ORDER BY co.rrf_score DESC)::INT AS rank
    FROM combined co
    ORDER BY co.rrf_score DESC
    LIMIT match_count;
END;
$$;
