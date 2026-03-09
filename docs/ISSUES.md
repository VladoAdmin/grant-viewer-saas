# ISSUES.md — Grant Viewer SaaS

## Found during Week 1 implementation

### ISSUE-001: Existing v2_call_chunks uses 1536-dim embeddings, not 3072
- **Impact:** PRD says 3072, but existing data uses text-embedding-3-small (1536).
- **Decision:** Keep 1536 for MVP. It's cheaper and existing 2528 chunks are already 1536-dim.
- **Action:** Updated hybrid_search RPC to use vector(1536). PRD Appendix should be corrected.

### ISSUE-002: v2_call_chunks column is "content", not "chunk_text"
- **Impact:** Old vectorize_calls_v3.py references `chunk_text` but the actual column is `content`.
- **Decision:** Used `content` throughout. Old references need updating.
- **Status:** ✅ Fixed in migration and all new code.

### ISSUE-003: Root __init__.py conflicts with pytest
- **Impact:** Old project root `__init__.py` has relative imports (`from .discovery import DiscoveryEngine`) that break pytest test collection.
- **Decision:** Renamed to `_old_init.py` to unblock testing. Legacy code may need updating.
- **Status:** ✅ Fixed.

### ISSUE-004: ITMS21 API does not return document attachments for all calls
- **Impact:** Some calls return 0 attachments from the API. PDF extraction and embedding will only work for calls with downloadable documents.
- **Decision:** This is expected behavior. The scraper logs calls without attachments but continues processing.
- **Status:** Not a bug, documented.

### ISSUE-005: grant_calls_v2.id is BIGINT, not INT
- **Impact:** find_duplicate_calls() RPC was created with INT return type, causing 400 errors.
- **Decision:** Fixed to use BIGINT.
- **Status:** ✅ Fixed.

### ISSUE-006: 1 duplicate detected in existing data
- **Impact:** Call #52 is a duplicate of call #50 (same title + announced_at).
- **Decision:** Dedup job merged it (soft-deleted #52).
- **Status:** ✅ Resolved.
