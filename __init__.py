"""
GrantBot V2 - Two-phase grant scraper
Discovery → Enrichment pipeline with LLM classification
"""

__version__ = "2.0.0"

from .discovery import DiscoveryEngine
from .enrichment import EnrichmentEngine
from .models import (
    DiscoveredCall,
    EnrichedCall,
    SourceConfig,
)
from .run_v2 import GrantBotV2

__all__ = [
    'DiscoveryEngine',
    'EnrichmentEngine',
    'GrantBotV2',
    'DiscoveredCall',
    'EnrichedCall',
    'SourceConfig',
]
