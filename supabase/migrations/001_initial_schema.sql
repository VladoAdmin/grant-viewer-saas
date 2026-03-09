-- Grant Viewer SaaS — Phase 1 Schema Migration
-- Run in Supabase SQL Editor
-- Note: grant_calls_v2, v2_call_chunks, grant_call_attachments already exist.
-- This migration ADDS missing tables and indexes.

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 1. grant_call_attributes (structured key-value data)
-- ============================================================
CREATE TABLE IF NOT EXISTS grant_call_attributes (
    id SERIAL PRIMARY KEY,
    grant_call_id INTEGER NOT NULL REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text',  -- text, number, date, json
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(grant_call_id, key)
);

CREATE INDEX IF NOT EXISTS idx_grant_call_attributes_call_id
    ON grant_call_attributes(grant_call_id);

-- ============================================================
-- 2. doc_classification (AI-classified documents)
-- ============================================================
CREATE TABLE IF NOT EXISTS doc_classification (
    id SERIAL PRIMARY KEY,
    grant_call_id INTEGER NOT NULL REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    attachment_id INTEGER REFERENCES grant_call_attachments(id) ON DELETE SET NULL,
    filename TEXT,
    doc_type TEXT NOT NULL DEFAULT 'unknown',  -- main, conditions, criteria, costs, skip
    confidence FLOAT DEFAULT 0.0,
    classified_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_classification_call_id
    ON doc_classification(grant_call_id);

-- ============================================================
-- 3. scraper_runs (admin status tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS scraper_runs (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',  -- running, success, error
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    calls_found INTEGER DEFAULT 0,
    calls_new INTEGER DEFAULT 0,
    calls_updated INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_scraper_runs_source
    ON scraper_runs(source);
CREATE INDEX IF NOT EXISTS idx_scraper_runs_started
    ON scraper_runs(started_at DESC);

-- ============================================================
-- 4. error_log (error tracking with error_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS error_log (
    id SERIAL PRIMARY KEY,
    error_id TEXT NOT NULL UNIQUE DEFAULT ('ERR-' || to_char(NOW(), 'YYYYMMDD') || '-' || LPAD(floor(random() * 10000)::text, 4, '0')),
    source TEXT,       -- scraper, extractor, embedder, api
    component TEXT,    -- specific module name
    severity TEXT DEFAULT 'error',  -- warning, error, critical
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE SET NULL,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_error_log_created
    ON error_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_log_resolved
    ON error_log(resolved) WHERE NOT resolved;

-- ============================================================
-- 5. Add doc_type column to v2_call_chunks if missing
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'v2_call_chunks' AND column_name = 'doc_type'
    ) THEN
        ALTER TABLE v2_call_chunks ADD COLUMN doc_type TEXT;
    END IF;
END $$;

-- ============================================================
-- 6. dedup_log (tracking deduplication operations)
-- ============================================================
CREATE TABLE IF NOT EXISTS dedup_log (
    id SERIAL PRIMARY KEY,
    original_call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE SET NULL,
    duplicate_call_id INTEGER,
    duplicate_title TEXT,
    match_reason TEXT,  -- title_match, url_match, code_match
    action TEXT DEFAULT 'merged',  -- merged, skipped, flagged
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 7. Fulltext search index on v2_call_chunks
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_v2_call_chunks_fts
    ON v2_call_chunks USING gin(to_tsvector('simple', coalesce(content, '')));

-- ============================================================
-- 8. Add soft-delete column to grant_calls_v2 for cleanup
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'grant_calls_v2' AND column_name = 'deleted_at'
    ) THEN
        ALTER TABLE grant_calls_v2 ADD COLUMN deleted_at TIMESTAMPTZ;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_grant_calls_v2_deleted
    ON grant_calls_v2(deleted_at) WHERE deleted_at IS NOT NULL;

-- ============================================================
-- 9. Hybrid search RPC function (vector + fulltext + RRF)
-- ============================================================
-- Drop old versions
DROP FUNCTION IF EXISTS hybrid_search_chunks(TEXT, vector(3072), FLOAT, INT, INT);
DROP FUNCTION IF EXISTS hybrid_search_chunks(TEXT, vector(1536), FLOAT, INT, INT);
DROP FUNCTION IF EXISTS hybrid_search_chunks(TEXT, vector(1536), FLOAT, INT, INT, TEXT);

CREATE OR REPLACE FUNCTION hybrid_search_chunks(
    query_text TEXT,
    query_embedding vector(1536),
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 10,
    call_id_filter INT DEFAULT NULL,
    doc_type_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    id INT,
    call_id INT,
    chunk_content TEXT,
    source TEXT,
    doc_type TEXT,
    similarity FLOAT,
    rank INT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            c.id::INT,
            c.call_id::INT,
            c.content AS chunk_content,
            c.source,
            c.doc_type,
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
            (COALESCE(v.similarity, 0) + COALESCE(t.similarity, 0) * 0.5)::FLOAT AS combined_score,
            (COALESCE(1.0 / (60 + v.vector_rank), 0) + COALESCE(1.0 / (60 + t.text_rank), 0))::FLOAT AS rrf_score
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.id = t.id
    )
    SELECT
        c.id,
        c.call_id,
        c.chunk_content,
        c.source,
        c.doc_type,
        c.combined_score AS similarity,
        ROW_NUMBER() OVER (ORDER BY c.rrf_score DESC)::INT AS rank
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 10. Cleanup function: soft-delete old calls
-- ============================================================
CREATE OR REPLACE FUNCTION cleanup_old_calls(months_threshold INT DEFAULT 12)
RETURNS TABLE (cleaned_count INT) AS $$
DECLARE
    cnt INT;
BEGIN
    UPDATE grant_calls_v2
    SET deleted_at = NOW()
    WHERE deleted_at IS NULL
      AND deadline_at IS NOT NULL
      AND deadline_at < NOW() - (months_threshold || ' months')::INTERVAL
      AND status IN ('uzavretá', 'zrušená', 'uzavretá', 'Uzavretá');

    GET DIAGNOSTICS cnt = ROW_COUNT;
    RETURN QUERY SELECT cnt;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 11. Hard-delete chunks for soft-deleted calls (3 months after soft-delete)
-- ============================================================
CREATE OR REPLACE FUNCTION hard_delete_old_chunks(months_after_softdelete INT DEFAULT 3)
RETURNS TABLE (deleted_chunks INT) AS $$
DECLARE
    cnt INT;
BEGIN
    DELETE FROM v2_call_chunks
    WHERE call_id IN (
        SELECT id FROM grant_calls_v2
        WHERE deleted_at IS NOT NULL
          AND deleted_at < NOW() - (months_after_softdelete || ' months')::INTERVAL
    );

    GET DIAGNOSTICS cnt = ROW_COUNT;
    RETURN QUERY SELECT cnt;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 12. Dedup detection function
-- ============================================================
CREATE OR REPLACE FUNCTION find_duplicate_calls()
RETURNS TABLE (
    original_id BIGINT,
    duplicate_id BIGINT,
    original_title TEXT,
    duplicate_title TEXT,
    match_type TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id AS original_id,
        b.id AS duplicate_id,
        a.title AS original_title,
        b.title AS duplicate_title,
        'title_date_match'::TEXT AS match_type
    FROM grant_calls_v2 a
    JOIN grant_calls_v2 b ON
        a.id < b.id
        AND LOWER(TRIM(a.title)) = LOWER(TRIM(b.title))
        AND a.announced_at = b.announced_at
        AND a.deleted_at IS NULL
        AND b.deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

-- Add deleted_at to v2_call_chunks if missing (for soft-delete awareness)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'v2_call_chunks' AND column_name = 'deleted_at'
    ) THEN
        ALTER TABLE v2_call_chunks ADD COLUMN deleted_at TIMESTAMPTZ;
    END IF;
END $$;

-- Grant permissions
GRANT EXECUTE ON FUNCTION hybrid_search_chunks TO anon, authenticated;
GRANT EXECUTE ON FUNCTION cleanup_old_calls TO authenticated;
GRANT EXECUTE ON FUNCTION hard_delete_old_chunks TO authenticated;
GRANT EXECUTE ON FUNCTION find_duplicate_calls TO authenticated;
