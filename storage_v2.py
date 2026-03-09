"""
Database storage layer for GrantBot V2
Uses Supabase REST API (same as v1, but for v2 tables)
"""
import json
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import requests

from .models import (
    DiscoveredCall,
    DiscoveryRun,
    EnrichedCall,
    EnrichmentRun,
    SourceConfig,
)


class StorageV2:
    """Database operations for GrantBot V2"""
    
    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise RuntimeError('SUPABASE_URL and SUPABASE_KEY must be set')
    
    def _headers(self) -> Dict[str, str]:
        return {
            'apikey': self.supabase_key,
            'Authorization': f'Bearer {self.supabase_key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        }
    
    def _post(self, table: str, data: Dict) -> List[Dict]:
        """Insert data into table"""
        url = f"{self.supabase_url}/rest/v1/{table}"
        payload = json.dumps(data, default=str)
        resp = requests.post(url, headers=self._headers(), data=payload, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.text else []
    
    def _patch(self, table: str, filters: Dict[str, Any], data: Dict) -> List[Dict]:
        """Update data in table"""
        url = f"{self.supabase_url}/rest/v1/{table}"
        params = {f'{k}': f'eq.{v}' for k, v in filters.items()}
        payload = json.dumps(data, default=str)
        resp = requests.patch(url, headers=self._headers(), params=params, data=payload, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.text else []
    
    def _get(self, table: str, filters: Optional[Dict] = None, 
             order: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """Query table"""
        url = f"{self.supabase_url}/rest/v1/{table}"
        params = {}
        if filters:
            params.update({f'{k}': f'eq.{v}' for k, v in filters.items()})
        if order:
            params['order'] = order
        if limit:
            params['limit'] = limit
        
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.text else []
    
    # =========================================================================
    # SOURCE CONFIG OPERATIONS
    # =========================================================================
    
    def get_sources(self, enabled_only: bool = True) -> List[SourceConfig]:
        """Get all configured sources"""
        if enabled_only:
            rows = self._get('v2_sources', filters={'enabled': 'true'})
        else:
            rows = self._get('v2_sources')
        return [SourceConfig.model_validate(r) for r in rows]
    
    def save_source(self, source: SourceConfig) -> SourceConfig:
        """Save or update source config"""
        data = source.model_dump(exclude={'id'}, exclude_none=True)
        # Try upsert
        url = f"{self.supabase_url}/rest/v1/v2_sources"
        headers = self._headers()
        headers['Prefer'] = 'resolution=merge-duplicates,return=representation'
        params = {'on_conflict': 'name'}
        
        resp = requests.post(url, headers=headers, params=params, data=json.dumps(data, default=str), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return SourceConfig.model_validate(result[0]) if result else source
    
    # =========================================================================
    # DISCOVERY OPERATIONS
    # =========================================================================
    
    def create_discovery_run(self) -> DiscoveryRun:
        """Start new discovery run"""
        data = {'status': 'running', 'started_at': 'now()'}
        result = self._post('v2_discovery_runs', data)
        return DiscoveryRun.model_validate(result[0])
    
    def update_discovery_run(self, run_id: UUID, **updates) -> None:
        """Update discovery run status"""
        updates.setdefault('finished_at', 'now()')
        self._patch('v2_discovery_runs', {'id': str(run_id)}, updates)
    
    def save_discovered_call(self, call: DiscoveredCall) -> DiscoveredCall:
        """Save discovered call"""
        data = call.model_dump(exclude={'id', 'discovered_at', 'classified_at'}, exclude_none=True)
        
        # Upsert on (source, call_url)
        url = f"{self.supabase_url}/rest/v1/v2_discovered_calls"
        headers = self._headers()
        headers['Prefer'] = 'resolution=merge-duplicates,return=representation'
        params = {'on_conflict': 'source,call_url'}
        
        # Note: PostgREST upsert will merge duplicates; do not include non-table fields.
        resp = requests.post(url, headers=headers, params=params, data=json.dumps(data, default=str), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return DiscoveredCall.model_validate(result[0]) if result else call
    
    def get_pending_discovered_calls(self, limit: int = 100) -> List[DiscoveredCall]:
        """Get discovered calls awaiting classification"""
        url = f"{self.supabase_url}/rest/v1/v2_discovered_calls"
        params = {
            'discovery_status': 'eq.pending',
            'order': 'discovered_at.asc',
            'limit': limit
        }
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        return [DiscoveredCall.model_validate(r) for r in rows]
    
    def get_qualified_calls(self, limit: int = 50) -> List[DiscoveredCall]:
        """Get calls ready for enrichment."""
        url = f"{self.supabase_url}/rest/v1/v2_calls_ready_for_enrichment"
        params = {'limit': limit}
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        fixed: List[DiscoveredCall] = []
        for r in rows:
            # v2_calls_ready_for_enrichment returns discovered_call_id, not id
            if r.get('discovered_call_id') and not r.get('id'):
                r = {**r, 'id': r['discovered_call_id']}
            fixed.append(DiscoveredCall.model_validate(r))
        return fixed
    
    def update_discovered_call(self, call_id: UUID, **updates) -> None:
        """Update discovered call"""
        self._patch('v2_discovered_calls', {'id': str(call_id)}, updates)
    
    # =========================================================================
    # ENRICHMENT OPERATIONS
    # =========================================================================
    
    def create_enrichment_run(self, discovery_run_id: Optional[UUID] = None) -> EnrichmentRun:
        """Start new enrichment run"""
        data = {
            'status': 'running',
            'started_at': 'now()',
            'discovery_run_id': str(discovery_run_id) if discovery_run_id else None
        }
        result = self._post('v2_enrichment_runs', data)
        return EnrichmentRun.model_validate(result[0])
    
    def update_enrichment_run(self, run_id: UUID, **updates) -> None:
        """Update enrichment run"""
        updates.setdefault('finished_at', 'now()')
        self._patch('v2_enrichment_runs', {'id': str(run_id)}, updates)
    
    def create_enriched_call(self, call: EnrichedCall) -> EnrichedCall:
        """Create enrichment record for a discovered call"""
        data = call.model_dump(
            exclude={'id', 'enrichment_started_at', 'enrichment_completed_at'},
            exclude_none=True
        )
        result = self._post('v2_enriched_calls', data)
        return EnrichedCall.model_validate(result[0]) if result else call
    
    def update_enriched_call(self, call_id: UUID, **updates) -> None:
        """Update enriched call"""
        self._patch('v2_enriched_calls', {'id': str(call_id)}, updates)
    
    def get_enriched_call_by_discovered(self, discovered_call_id: UUID) -> Optional[EnrichedCall]:
        """Get enrichment record by discovered call ID"""
        rows = self._get('v2_enriched_calls', filters={'discovered_call_id': str(discovered_call_id)})
        return EnrichedCall.model_validate(rows[0]) if rows else None
    
    # =========================================================================
    # AUDIT / DEBUGGING
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        # This would ideally be done via RPC, but we'll do simple counts
        stats = {
            'discovered_total': 0,
            'discovered_qualified': 0,
            'discovered_pending': 0,
            'enriched_total': 0,
            'enriched_failed': 0,
            'manual_audit_queue': 0
        }
        
        # Count discovered
        url = f"{self.supabase_url}/rest/v1/v2_discovered_calls"
        params = {'select': 'count', 'discovery_status': 'eq.qualified'}
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 200:
            stats['discovered_qualified'] = len(resp.json())
        
        return stats
    
    def get_manual_audit_queue(self, limit: int = 20) -> List[Dict]:
        """Get calls requiring manual review"""
        url = f"{self.supabase_url}/rest/v1/v2_manual_audit_queue"
        params = {'limit': limit}
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()


# Singleton
_storage: Optional[StorageV2] = None


def get_storage() -> StorageV2:
    """Get or create storage instance"""
    global _storage
    if _storage is None:
        _storage = StorageV2()
    return _storage
