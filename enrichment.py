"""
GrantBot V2: Enrichment Phase
Deep extraction of grant call details
"""
import asyncio
from datetime import datetime
from typing import List, Optional

import httpx
from playwright.async_api import async_playwright, Page

from .llm_client import get_llm_client
from .models import (
    DiscoveredCall,
    EnrichedCall,
    EnrichmentRun,
    EnrichmentStatus,
    ExtractionMethod,
    LLMExtractionResult,
)
from .storage_v2 import get_storage


class EnrichmentEngine:
    """Engine for enriching discovered calls with full details"""
    
    def __init__(self):
        self.storage = get_storage()
        self.llm = get_llm_client()
        self.playwright = None
        self.browser = None
    
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        return self
    
    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def run_enrichment(
        self,
        discovery_run_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> EnrichmentRun:
        """Run enrichment on qualified discovered calls"""
        # Create run record
        run = self.storage.create_enrichment_run(
            discovery_run_id=discovery_run_id
        )
        print(f"🚀 Enrichment run started: {run.id}")
        
        try:
            # Get qualified calls
            calls = self.storage.get_qualified_calls(limit=limit or 50)
            print(f"📋 Found {len(calls)} calls to enrich")
            
            if not calls:
                self.storage.update_enrichment_run(run.id, status='completed')
                return run
            
            success_count = 0
            failed_count = 0
            manual_count = 0
            
            for call in calls:
                result = await self._enrich_call(call, run.id)
                
                if result.enrichment_status == EnrichmentStatus.ENRICHED:
                    success_count += 1
                elif result.enrichment_status == EnrichmentStatus.MANUAL_AUDIT:
                    manual_count += 1
                else:
                    failed_count += 1
            
            # Complete run
            self.storage.update_enrichment_run(
                run.id,
                status='completed',
                calls_processed=len(calls),
                calls_success=success_count,
                calls_failed=failed_count,
                calls_manual=manual_count
            )
            
            print(f"\n✅ Enrichment completed!")
            print(f"   Processed: {len(calls)}")
            print(f"   Success: {success_count}")
            print(f"   Failed: {failed_count}")
            print(f"   Manual audit: {manual_count}")
            
        except Exception as e:
            self.storage.update_enrichment_run(run.id, status='failed', error_message=str(e))
            raise
        
        return run
    
    async def _enrich_call(
        self,
        discovered: DiscoveredCall,
        run_id
    ) -> EnrichedCall:
        """Enrich a single discovered call"""
        print(f"\n🔍 Enriching: {discovered.title or discovered.call_url}")
        
        # Create or get enrichment record
        existing = self.storage.get_enriched_call_by_discovered(discovered.id)
        if existing:
            enriched = existing
        else:
            enriched = EnrichedCall(
                discovered_call_id=discovered.id,
                enrichment_status=EnrichmentStatus.ENRICHING,
                enrichment_run_id=run_id,
                enrichment_started_at=datetime.utcnow()
            )
            enriched = self.storage.create_enriched_call(enriched)
        
        try:
            # Fetch page content (use Playwright for JS-heavy sites)
            html_content = await self._fetch_page(discovered.call_url)
            
            if not html_content or len(html_content) < 500:
                raise ValueError("Failed to fetch page or content too short")
            
            # Extract with LLM
            extraction = self.llm.extract_grant_details(
                html_content=html_content,
                url=discovered.call_url,
                title_hint=discovered.title
            )
            
            # Convert to model
            enriched = self._apply_extraction(enriched, extraction, html_content)
            
            # Determine status
            if enriched.extraction_confidence and enriched.extraction_confidence < 0.3:
                enriched.enrichment_status = EnrichmentStatus.MANUAL_AUDIT
                print(f"   ⚠️  Low confidence → manual audit")
            else:
                enriched.enrichment_status = EnrichmentStatus.ENRICHED
                print(f"   ✅ Enriched (conf: {enriched.extraction_confidence:.2f})")
            
            enriched.enrichment_completed_at = datetime.utcnow()
            
            # Update database
            self.storage.update_enriched_call(
                enriched.id,
                **enriched.model_dump(
                    include={
                        'title_clean', 'description', 'description_html',
                        'deadline_at', 'announced_at', 'extended_deadline_at',
                        'provider', 'provider_org', 'total_allocation',
                        'min_grant', 'max_grant', 'cofinancing_percent',
                        'eligible_applicants', 'eligible_applicants_text',
                        'sector_tags', 'area_tags',
                        'conditions', 'evaluation_criteria',
                        'contact_person', 'contact_email', 'contact_phone', 'contact_web',
                        'attachments',
                        'enrichment_status', 'extraction_confidence', 'extraction_model',
                        'enrichment_completed_at',
                        'raw_html', 'raw_extraction'
                    },
                    exclude_none=True
                )
            )
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            
            # Increment retry count
            enriched.retry_count = (enriched.retry_count or 0) + 1
            enriched.error_message = str(e)
            
            # Mark for manual audit after 3 retries
            if enriched.retry_count >= 3:
                enriched.enrichment_status = EnrichmentStatus.MANUAL_AUDIT
                print(f"   📋 Marked for manual audit (retry {enriched.retry_count})")
            else:
                enriched.enrichment_status = EnrichmentStatus.FAILED
            
            self.storage.update_enriched_call(
                enriched.id,
                retry_count=enriched.retry_count,
                error_message=enriched.error_message,
                enrichment_status=enriched.enrichment_status
            )
        
        return enriched
    
    async def _fetch_page(self, url: str) -> str:
        """Fetch page content using Playwright (for JS-heavy sites)"""
        context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        try:
            page = await context.new_page()
            
            # Navigate and wait for content
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait a bit for any lazy-loaded content
            await asyncio.sleep(2)
            
            # Get full HTML
            html = await page.content()
            
            await page.close()
            return html
            
        finally:
            await context.close()
    
    def _apply_extraction(
        self,
        enriched: EnrichedCall,
        extraction: LLMExtractionResult,
        raw_html: str
    ) -> EnrichedCall:
        """Apply LLM extraction result to enriched call"""
        from datetime import date
        from decimal import Decimal, InvalidOperation
        
        def parse_date(d: Optional[str]) -> Optional[date]:
            if not d:
                return None
            try:
                return date.fromisoformat(d[:10])  # YYYY-MM-DD
            except (ValueError, TypeError):
                return None
        
        def parse_decimal(v: Optional[str]) -> Optional[Decimal]:
            if v is None:
                return None
            try:
                # Remove spaces, replace comma with dot
                cleaned = str(v).replace(' ', '').replace(',', '.').replace('€', '').replace('EUR', '')
                return Decimal(cleaned)
            except (InvalidOperation, ValueError):
                return None
        
        # Core fields
        enriched.title_clean = extraction.title_clean or enriched.title_clean
        enriched.description = extraction.description
        enriched.description_html = None  # We could store raw HTML separately
        
        # Dates
        enriched.deadline_at = parse_date(extraction.deadline_at)
        enriched.announced_at = parse_date(extraction.announced_at)
        enriched.extended_deadline_at = parse_date(extraction.extended_deadline_at)
        
        # Provider and funding
        enriched.provider = extraction.provider
        enriched.provider_org = extraction.provider_org
        enriched.total_allocation = parse_decimal(extraction.total_allocation)
        enriched.min_grant = parse_decimal(extraction.min_grant)
        enriched.max_grant = parse_decimal(extraction.max_grant)
        enriched.cofinancing_percent = parse_decimal(extraction.cofinancing_percent)
        
        # Eligibility
        enriched.eligible_applicants = extraction.eligible_applicants
        enriched.eligible_applicants_text = extraction.eligible_applicants_text
        
        # Categorization
        enriched.sector_tags = extraction.sector_tags
        enriched.area_tags = extraction.area_tags
        
        # Conditions
        enriched.conditions = extraction.conditions
        enriched.evaluation_criteria = extraction.evaluation_criteria
        
        # Contact
        enriched.contact_person = extraction.contact_person
        enriched.contact_email = extraction.contact_email
        enriched.contact_phone = extraction.contact_phone
        enriched.contact_web = extraction.contact_web
        
        # Attachments
        enriched.attachments = extraction.attachments
        
        # Metadata
        enriched.extraction_confidence = extraction.extraction_confidence
        enriched.extraction_method = ExtractionMethod.LLM
        enriched.extraction_model = 'gpt-4o-mini'  # TODO: get from config
        
        # Raw data
        enriched.raw_html = raw_html[:50000] if raw_html else None  # Truncate
        enriched.raw_extraction = extraction.model_dump()
        
        return enriched


# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """Run enrichment from command line"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GrantBot V2 Enrichment')
    parser.add_argument('--discovery-run', help='Process calls from specific discovery run')
    parser.add_argument('--limit', type=int, default=50, help='Max calls to process')
    parser.add_argument('--call-id', help='Process specific discovered call ID')
    args = parser.parse_args()
    
    async with EnrichmentEngine() as engine:
        if args.call_id:
            # Process single call
            storage = get_storage()
            calls = storage._get('v2_discovered_calls', filters={'id': args.call_id})
            if calls:
                from uuid import UUID
                call = DiscoveredCall.model_validate(calls[0])
                await engine._enrich_call(call, None)
            else:
                print(f"Call {args.call_id} not found")
        else:
            # Run full enrichment
            await engine.run_enrichment(
                discovery_run_id=args.discovery_run,
                limit=args.limit
            )


if __name__ == '__main__':
    asyncio.run(main())
