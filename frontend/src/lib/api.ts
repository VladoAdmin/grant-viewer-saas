/**
 * API client for the Grant Viewer backend.
 */

const API_BASE = import.meta.env.VITE_API_URL || '/api';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(body.error || body.message || `API error ${resp.status}`);
  }
  return resp.json();
}

// Types
export interface GrantCall {
  id: number;
  source: string;
  source_url: string;
  call_url: string;
  title: string;
  announced_at: string | null;
  deadline_at: string | null;
  provider: string | null;
  call_type: string | null;
  total_allocation: string | null;
  status: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallDetail {
  call: GrantCall;
  attributes: Record<string, string>;
  attachments: Array<{
    id: number;
    name: string;
    url: string;
    file_type: string | null;
  }>;
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

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  took_ms: number;
  total: number;
}

export interface CallsResponse {
  data: GrantCall[];
  total: number;
  page: number;
  limit: number;
}

export interface AdminStatus {
  sources: Record<string, unknown>;
  recent_runs: unknown[];
  stats: {
    total_calls: number;
    total_chunks: number;
  };
}

// API functions
export function getCalls(params: Record<string, string> = {}): Promise<CallsResponse> {
  const qs = new URLSearchParams(params).toString();
  return apiFetch(`/calls${qs ? '?' + qs : ''}`);
}

export function getCallDetail(id: number): Promise<CallDetail> {
  return apiFetch(`/calls/${id}`);
}

export function search(query: string, options?: { call_id?: number; doc_type?: string; limit?: number }): Promise<SearchResponse> {
  return apiFetch('/search', {
    method: 'POST',
    body: JSON.stringify({ query, ...options }),
  });
}

export function getAdminStatus(): Promise<AdminStatus> {
  return apiFetch('/admin/status');
}

export function triggerScraper(source: string): Promise<{ status: string; message: string }> {
  return apiFetch('/admin/trigger', {
    method: 'POST',
    body: JSON.stringify({ source }),
  });
}

export function submitFeedback(data: {
  call_id?: number;
  type: string;
  message: string;
  contact?: string;
}): Promise<{ status: string; message: string }> {
  return apiFetch('/feedback', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getExportPdfUrl(id: number): string {
  return `${API_BASE}/calls/${id}/export-pdf`;
}
