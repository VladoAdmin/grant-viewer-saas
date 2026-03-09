"""
GrantBot V2: Discovery Phase
Finds and classifies grant calls from source URLs
"""
import asyncio
import hashlib
from datetime import datetime
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .llm_client import get_llm_client
from .models import (
    CallStatus,
    DiscoveredCall,
    DiscoveredLink,
    DiscoveryRun,
    DiscoveryStatus,
    LLMClassificationResult,
    SourceConfig,
)
from .storage_v2 import get_storage


class DiscoveryEngine:
    """Engine for discovering grant calls from sources"""
    
    def __init__(self):
        self.storage = get_storage()
        self.llm = get_llm_client()
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        self.playwright = None
        self.browser = None
    
    async def __aenter__(self):
        # Lazy init Playwright only if we need dynamic sources
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        return self
    
    async def __aexit__(self, *args):
        try:
            await self.http_client.aclose()
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
    
    async def run_discovery(self, source_names: Optional[List[str]] = None) -> DiscoveryRun:
        """Run discovery on all or specified sources"""
        # Create run record
        run = self.storage.create_discovery_run()
        print(f"🚀 Discovery run started: {run.id}")
        
        try:
            # Get sources
            sources = self.storage.get_sources(enabled_only=True)
            if source_names:
                sources = [s for s in sources if s.name in source_names]
            
            total_found = 0
            total_classified = 0
            total_qualified = 0
            
            for source in sources:
                print(f"\n📡 Processing: {source.name} ({source.url})")
                try:
                    found, classified, qualified = await self._process_source(source, run.id)
                    total_found += found
                    total_classified += classified
                    total_qualified += qualified
                    
                    # Update source stats
                    self.storage._patch('v2_sources', {'name': source.name}, {
                        'last_discovery_at': 'now()',
                        'last_discovery_count': found
                    })
                except Exception as e:
                    print(f"❌ Error processing {source.name}: {e}")
            
            # Complete run
            self.storage.update_discovery_run(
                run.id,
                status='completed',
                sources_processed=len(sources),
                links_found=total_found,
                links_classified=total_classified,
                links_qualified=total_qualified
            )
            
            print(f"\n✅ Discovery completed!")
            print(f"   Sources: {len(sources)}")
            print(f"   Links found: {total_found}")
            print(f"   Classified: {total_classified}")
            print(f"   Qualified: {total_qualified}")
            
        except Exception as e:
            self.storage.update_discovery_run(run.id, status='failed', error_message=str(e))
            raise
        
        return run
    
    async def _process_source(self, source: SourceConfig, run_id) -> tuple[int, int, int]:
        """Process single source, return (found, classified, qualified)"""
        # Fetch page
        try:
            html = await self._fetch_page(source)
        except Exception as e:
            print(f"   ⚠️  Failed to fetch: {e}")
            return 0, 0, 0
        
        # Parse links
        links = self._extract_links(html, source.url, source.discovery_selector)
        print(f"   🔗 Found {len(links)} links")
        
        if not links:
            return 0, 0, 0
        
        # Classify links with LLM
        classified_count = 0
        qualified_count = 0
        
        for link in links:
            try:
                # Check if already exists
                existing = self.storage._get(
                    'v2_discovered_calls',
                    filters={'source': source.name, 'call_url': link.url}
                )
                if existing:
                    print(f"   ⏭️  Skipping (exists): {link.url[:60]}...")
                    continue
                
                # Classify with LLM
                classification = self.llm.classify_grant_link(
                    url=link.url,
                    title=link.title,
                    anchor_text=link.anchor_text,
                    surrounding_text=link.surrounding_text
                )
                classified_count += 1
                
                # Determine status
                if classification.is_grant_call and classification.call_status in (CallStatus.OPEN, CallStatus.PLANNED, CallStatus.UNKNOWN):
                    discovery_status = DiscoveryStatus.QUALIFIED
                    qualified_count += 1
                    print(f"   ✅ Qualified ({classification.call_status}): {link.title[:50]}...")
                elif classification.is_grant_call:
                    discovery_status = DiscoveryStatus.REJECTED  # Closed
                    print(f"   ⏭️  Closed: {link.title[:50]}...")
                else:
                    discovery_status = DiscoveryStatus.REJECTED
                
                # Save to database
                call = DiscoveredCall(
                    source=source.name,
                    source_url=source.url,
                    call_url=link.url,
                    title=link.title,
                    call_status=classification.call_status if classification.is_grant_call else CallStatus.UNKNOWN,
                    llm_confidence=classification.confidence,
                    llm_reasoning=classification.reasoning,
                    raw_html_snippet=link.html_snippet[:2000] if link.html_snippet else None,
                    anchor_text=link.anchor_text,
                    surrounding_text=link.surrounding_text,
                    discovery_status=discovery_status,
                    discovery_run_id=run_id,
                    discovered_at=datetime.utcnow(),
                    classified_at=datetime.utcnow()
                )
                self.storage.save_discovered_call(call)
                
            except Exception as e:
                print(f"   ❌ Error classifying {link.url}: {e}")
                # Save as error for retry
                call = DiscoveredCall(
                    source=source.name,
                    source_url=source.url,
                    call_url=link.url,
                    title=link.title,
                    discovery_status=DiscoveryStatus.ERROR,
                    discovery_run_id=run_id,
                    error_message=str(e),
                    discovered_at=datetime.utcnow()
                )
                self.storage.save_discovered_call(call)
        
        return len(links), classified_count, qualified_count

    async def _fetch_page(self, source: SourceConfig) -> str:
        """Fetch page HTML. Uses Playwright for dynamic sources, httpx for static."""
        if getattr(source, 'source_type', None) and str(source.source_type) == 'dynamic':
            context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            try:
                page = await context.new_page()
                await page.goto(source.url, wait_until='networkidle', timeout=45000)
                await asyncio.sleep(2)
                return await page.content()
            finally:
                await context.close()
        else:
            response = await self.http_client.get(source.url)
            response.raise_for_status()
            return response.text
    
    def _extract_links(
        self,
        html: str,
        base_url: str,
        selector: Optional[str] = None
    ) -> List[DiscoveredLink]:
        """Extract links from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        links: List[DiscoveredLink] = []
        seen_urls: Set[str] = set()
        
        # Use selector if provided, otherwise all links
        if selector:
            elements = soup.select(selector)
        else:
            elements = soup.find_all('a', href=True)
        
        for elem in elements:
            href = elem.get('href')
            if not href:
                continue
            
            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            
            # Skip non-HTTP, anchors, duplicates
            if not full_url.startswith(('http://', 'https://')):
                continue
            if '#' in full_url.split('/')[-1]:
                continue
            if full_url in seen_urls:
                continue
            
            # Skip common non-grant URLs
            if self._is_noise_url(full_url):
                continue
            
            seen_urls.add(full_url)
            
            # Extract context
            title = elem.get('title')
            anchor_text = elem.get_text(strip=True)
            
            # Get surrounding text (parent element)
            parent = elem.parent
            surrounding = ''
            if parent:
                surrounding = parent.get_text(separator=' ', strip=True)
            
            # HTML snippet for debugging
            snippet = str(elem)[:500]
            
            links.append(DiscoveredLink(
                url=full_url,
                title=title,
                anchor_text=anchor_text[:200] if anchor_text else None,
                surrounding_text=surrounding[:500] if surrounding else None,
                html_snippet=snippet
            ))
        
        return links
    
    def _is_noise_url(self, url: str) -> bool:
        """Check if URL is likely not a grant call"""
        noise_patterns = [
            '/wp-content/', '/wp-includes/', '/wp-json/',
            '/assets/', '/images/', '/css/', '/js/',
            'facebook.com', 'twitter.com', 'linkedin.com',
            'youtube.com', 'instagram.com',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx',
            'mailto:', 'tel:',
            '/cookie', '/privacy', '/terms', '/gdpr',
            '/login', '/register', '/search',
        ]
        url_lower = url.lower()
        return any(p in url_lower for p in noise_patterns)


# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """Run discovery from command line"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GrantBot V2 Discovery')
    parser.add_argument('--sources', nargs='+', help='Specific sources to process')
    parser.add_argument('--init-sources', action='store_true', help='Initialize default sources')
    args = parser.parse_args()
    
    if args.init_sources:
        print("📝 Initializing default sources...")
        storage = get_storage()
        default_sources = [
            SourceConfig(name='planobnovy', url='https://www.planobnovy.sk/vyzvy/'),
            SourceConfig(name='mirri', url='https://www.mirri.gov.sk/'),
            SourceConfig(name='vvi', url='https://www.vvi.gov.sk/', source_type='dynamic'),
            SourceConfig(name='itms21', url='https://www.itms2014.gov.sk/', source_type='dynamic'),
            SourceConfig(name='audiovizualnyfond', url='https://www.audiovizualnyfond.sk/'),
        ]
        for src in default_sources:
            storage.save_source(src)
            print(f"   ✓ {src.name}")
        return
    
    async with DiscoveryEngine() as engine:
        await engine.run_discovery(source_names=args.sources)


if __name__ == '__main__':
    asyncio.run(main())
