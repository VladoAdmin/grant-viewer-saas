# TASK-024: End-to-End Validation Results

**Date:** 2026-03-09  
**Tester:** Kodi Coder (automated)  
**Environment:** Local (srv1319479), Supabase cloud DB

## Test Summary

| # | Test | Status | Details |
|---|------|--------|---------|
| 1 | API Health Check | ✅ PASS | GET /api/health returns 200 |
| 2 | List Calls | ✅ PASS | 122 calls in DB, pagination works |
| 3 | Call Detail (rich data) | ✅ PASS | ID=343, provider + deadline + status + allocation |
| 4 | Call Detail (attributes) | ✅ PASS | ID=1, 6 attributes extracted (Program, Kód výzvy, Miesto, Alokácia EÚ/ŠR, Špecifický cieľ) |
| 5 | Filter by Source | ✅ PASS | portal.itms21.sk filter returns only ITMS21 calls |
| 6 | Hybrid Search | ✅ PASS | "oprávnení žiadatelia" returns 5 results in 1.0s |
| 7 | PDF Export | ✅ PASS | 2804 bytes PDF generated for call ID=1 |
| 8 | Admin Status | ✅ PASS | 122 calls, 2528 chunks, 2 sources |
| 9 | Feedback Submission | ✅ PASS | POST /api/feedback accepted |
| 10 | 404 Handling | ✅ PASS | Unknown routes return proper error |

## Backend API Tests (vitest)

```
✓ src/__tests__/api.test.ts (16 tests) 1895ms
  ✓ API Health > GET /api/health returns 200
  ✓ GET /api/calls > returns a list of calls with pagination
  ✓ GET /api/calls > filters by source
  ✓ GET /api/calls > handles page parameter
  ✓ GET /api/calls/:id > returns 400 for invalid ID
  ✓ GET /api/calls/:id > returns 404 for non-existent ID
  ✓ GET /api/calls/:id > returns call detail for valid ID
  ✓ POST /api/search > returns 400 for missing query
  ✓ POST /api/search > returns 400 for empty query
  ✓ POST /api/search > returns search results for valid query
  ✓ GET /api/calls/:id/export-pdf > returns PDF for valid call
  ✓ GET /api/admin/status > returns status with sources and stats
  ✓ POST /api/admin/trigger > returns 400 for invalid source
  ✓ POST /api/feedback > returns 400 for missing message
  ✓ POST /api/feedback > accepts valid feedback
  ✓ 404 handling > returns 404 for unknown routes

Test Files  1 passed (1)
     Tests  16 passed (16)
```

## Frontend Tests (vitest)

```
✓ src/components/__tests__/CallCard.test.tsx (5 tests)
✓ src/components/__tests__/ChunkResult.test.tsx (4 tests)
✓ src/components/__tests__/FeedbackModal.test.tsx (4 tests)
✓ src/components/__tests__/FilterBar.test.tsx (4 tests)
✓ src/pages/__tests__/Help.test.tsx (3 tests)

Test Files  5 passed (5)
     Tests  20 passed (20)
```

## Database State

- **Grant calls:** 122 (all from portal.itms21.sk)
- **Chunks:** 2,528 (3072-dim embeddings)
- **Scraper runs:** 2+ logged
- **Sources:** portal.itms21.sk

## ITMS21 Attribute Coverage

3 test calls freshly scraped with attributes:

| Attribute | Call 1 | Call 2 | Call 5 |
|-----------|--------|--------|--------|
| Program | ✅ | ✅ | ✅ |
| Kód výzvy | ✅ | ✅ | ✅ |
| Miesto realizácie | ✅ | ✅ | ✅ |
| Alokácia EÚ | ✅ | ✅ | ✅ |
| Alokácia ŠR | ✅ | ✅ | ✅ |
| Špecifický cieľ | ✅ | ✅ | ✅ |

**Note:** ITMS21 API returns limited data for many fields (deadline, status, eligible applicants are often null). This is a data source limitation, not a scraper issue. The old data in the DB (from the original scraper) has richer provider/deadline/status from an earlier API version.

## Search Performance

| Query | Results | Time |
|-------|---------|------|
| "oprávnení žiadatelia" | 5 | 1.0s |
| "dotácia na energetiku" | 3 | 4.3s |
| "dotácia" | 3 | 1.0s |

## Known Issues

1. **ITMS21 API sparse data:** Many fields (deadline, status, eligible applicants) are null in the API. Consider enriching from portal HTML in Phase 2.
2. **RPC function overload:** Old hybrid_search_chunks overload exists in DB. Resolved by always passing all params. Should clean up in Phase 2.
3. **Embedding dimension:** DB has 3072-dim vectors (text-embedding-3-large), scraper config says 1536. Backend uses correct 3072 for search.
