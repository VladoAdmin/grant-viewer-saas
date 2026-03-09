"""
GrantBot V2: Main orchestrator
Runs discovery followed by enrichment
"""
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

import requests

from .discovery import DiscoveryEngine
from .enrichment import EnrichmentEngine
from .storage_v2 import get_storage


class GrantBotV2:
    """Main orchestrator for two-phase scraping"""
    
    def __init__(self):
        self.storage = get_storage()
    
    async def run_full_pipeline(
        self,
        source_names: Optional[list] = None,
        enrichment_limit: Optional[int] = None,
        skip_discovery: bool = False,
        skip_enrichment: bool = False
    ):
        """Run complete discovery → enrichment pipeline"""
        print("=" * 60)
        print(f"🤖 GrantBot V2 Pipeline Started")
        print(f"   Time: {datetime.utcnow().isoformat()}")
        print("=" * 60)
        
        discovery_run = None
        
        # Phase 1: Discovery
        if not skip_discovery:
            print("\n" + "=" * 60)
            print("📡 PHASE 1: DISCOVERY")
            print("=" * 60)
            
            async with DiscoveryEngine() as engine:
                discovery_run = await engine.run_discovery(source_names=source_names)
            
            if discovery_run.status == 'failed':
                print("\n❌ Discovery failed, aborting pipeline")
                return
        else:
            print("\n⏭️  Skipping discovery phase")
        
        # Phase 2: Enrichment
        if not skip_enrichment:
            print("\n" + "=" * 60)
            print("🔍 PHASE 2: ENRICHMENT")
            print("=" * 60)
            
            async with EnrichmentEngine() as engine:
                await engine.run_enrichment(
                    discovery_run_id=discovery_run.id if discovery_run else None,
                    limit=enrichment_limit
                )
        else:
            print("\n⏭️  Skipping enrichment phase")
        
        print("\n" + "=" * 60)
        print("✅ Pipeline completed!")
        print("=" * 60)
        
        # Print summary
        await self._print_summary()
    
    async def _print_summary(self):
        """Print pipeline statistics"""
        stats = self.storage.get_stats()
        
        print("\n📊 Summary:")
        print(f"   Discovered (qualified): {stats.get('discovered_qualified', 0)}")
        print(f"   Enriched: {stats.get('enriched_total', 0)}")
        print(f"   Failed: {stats.get('enriched_failed', 0)}")
        print(f"   Manual audit: {stats.get('manual_audit_queue', 0)}")


def setup_environment():
    """Check and setup required environment variables"""
    required = ['SUPABASE_URL', 'SUPABASE_KEY']
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("   Please set them in .env file or export them")
        sys.exit(1)
    
    # Optional: LLM config
    provider = os.getenv('LLM_PROVIDER', 'ollama')
    if provider == 'ollama':
        # Check Ollama availability
        try:
            resp = requests.get('http://127.0.0.1:11434/api/tags', timeout=5)
            models = [m['name'] for m in resp.json().get('models', [])]
            print(f"✅ Ollama running, models: {', '.join(models)}")
        except Exception:
            print("⚠️  Warning: Ollama not reachable at http://127.0.0.1:11434")
            print("   LLM classification/extraction will fail!")
    elif not os.getenv('OPENROUTER_API_KEY') and not os.getenv('OPENAI_API_KEY'):
        print("⚠️  Warning: No LLM API key found (OPENROUTER_API_KEY or OPENAI_API_KEY)")
        print("   Discovery classification will fail!")


async def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='GrantBot V2 - Two-phase grant scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline
  python -m v2.run_v2
  
  # Run only discovery
  python -m v2.run_v2 --skip-enrichment
  
  # Run only enrichment (on previously discovered)
  python -m v2.run_v2 --skip-discovery
  
  # Process specific sources
  python -m v2.run_v2 --sources planobnovy mirri
  
  # Initialize sources
  python -m v2.discovery --init-sources
        """
    )
    
    parser.add_argument('--sources', nargs='+', help='Specific sources to process')
    parser.add_argument('--skip-discovery', action='store_true', help='Skip discovery phase')
    parser.add_argument('--skip-enrichment', action='store_true', help='Skip enrichment phase')
    parser.add_argument('--enrichment-limit', type=int, help='Limit enrichment to N calls')
    parser.add_argument('--init-db', action='store_true', help='Apply database migrations')
    
    args = parser.parse_args()
    
    setup_environment()
    
    # Apply migrations if requested
    if args.init_db:
        print("📦 Applying database migrations...")
        # This would run the SQL files
        print("   (Run manually: psql $DATABASE_URL -f sql/migrations_v2/*.sql)")
    
    # Run pipeline
    bot = GrantBotV2()
    await bot.run_full_pipeline(
        source_names=args.sources,
        enrichment_limit=args.enrichment_limit,
        skip_discovery=args.skip_discovery,
        skip_enrichment=args.skip_enrichment
    )


if __name__ == '__main__':
    asyncio.run(main())
