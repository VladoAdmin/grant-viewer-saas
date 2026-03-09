"""
Pydantic models for GrantBot V2
Two-phase scraping: Discovery → Enrichment
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class CallStatus(str, Enum):
    OPEN = "open"
    PLANNED = "planned"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class DiscoveryStatus(str, Enum):
    PENDING = "pending"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    ERROR = "error"


class EnrichmentStatus(str, Enum):
    PENDING = "pending"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    FAILED = "failed"
    MANUAL_AUDIT = "manual_audit"


class ExtractionMethod(str, Enum):
    LLM = "llm"
    TEMPLATE = "template"
    MANUAL = "manual"


class SourceType(str, Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


# ============================================================================
# DISCOVERY MODELS
# ============================================================================

class DiscoveredLink(BaseModel):
    """Raw link found on source page"""
    url: str
    title: Optional[str] = None
    anchor_text: Optional[str] = None
    surrounding_text: Optional[str] = None
    html_snippet: Optional[str] = None


class LLMClassificationResult(BaseModel):
    """LLM classification output for a discovered link"""
    is_grant_call: bool = Field(description="Is this URL a grant call page?")
    call_status: CallStatus = Field(description="Status of the call: open, planned, closed")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    reasoning: str = Field(description="Brief explanation of the classification")
    
    # Optional extracted fields even at discovery phase
    deadline: Optional[str] = None
    provider_hint: Optional[str] = None


class DiscoveredCall(BaseModel):
    """Database model for discovered calls"""
    id: Optional[UUID] = None
    source: str
    source_url: str
    call_url: str
    title: Optional[str] = None
    
    # LLM classification
    call_status: Optional[CallStatus] = None
    llm_confidence: Optional[float] = None
    llm_reasoning: Optional[str] = None
    
    # Raw content
    raw_html_snippet: Optional[str] = None
    anchor_text: Optional[str] = None
    surrounding_text: Optional[str] = None
    
    # State
    discovery_status: DiscoveryStatus = DiscoveryStatus.PENDING
    discovery_run_id: Optional[UUID] = None
    
    # Timestamps
    discovered_at: Optional[datetime] = None
    classified_at: Optional[datetime] = None
    
    # Audit
    error_message: Optional[str] = None
    retry_count: int = 0


class SourceConfig(BaseModel):
    """Configuration for a grant source"""
    name: str
    url: str
    source_type: SourceType = SourceType.STATIC
    enabled: bool = True
    discovery_selector: Optional[str] = None  # CSS selector for links
    
    # Optional: custom extraction hints
    title_selector: Optional[str] = None
    date_format: Optional[str] = None


# ============================================================================
# ENRICHMENT MODELS
# ============================================================================

class Attachment(BaseModel):
    """Document attachment"""
    name: str
    url: str
    file_type: Optional[str] = None
    size_bytes: Optional[int] = None


class LLMExtractionResult(BaseModel):
    """LLM extraction output for enrichment phase"""
    # Core
    title_clean: Optional[str] = None
    description: Optional[str] = None
    
    # Dates (ISO format strings)
    deadline_at: Optional[str] = None
    announced_at: Optional[str] = None
    extended_deadline_at: Optional[str] = None
    
    # Provider and funding
    provider: Optional[str] = None
    provider_org: Optional[str] = None
    total_allocation: Optional[Decimal] = None
    min_grant: Optional[Decimal] = None
    max_grant: Optional[Decimal] = None
    cofinancing_percent: Optional[Decimal] = None
    
    # Eligibility
    eligible_applicants: List[str] = Field(default_factory=list)
    eligible_applicants_text: Optional[str] = None
    
    # Categorization
    sector_tags: List[str] = Field(default_factory=list)
    area_tags: List[str] = Field(default_factory=list)
    
    # Conditions and criteria
    conditions: Optional[Dict[str, Any]] = None
    evaluation_criteria: Optional[str] = None
    
    # Contact
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_web: Optional[str] = None
    
    # Attachments found
    attachments: List[Attachment] = Field(default_factory=list)
    
    # Metadata
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    extraction_notes: Optional[str] = None


class EnrichedCall(BaseModel):
    """Database model for enriched calls"""
    id: Optional[UUID] = None
    discovered_call_id: UUID
    
    # Core fields
    title_clean: Optional[str] = None
    description: Optional[str] = None
    description_html: Optional[str] = None
    
    # Dates
    deadline_at: Optional[date] = None
    announced_at: Optional[date] = None
    extended_deadline_at: Optional[date] = None
    
    # Provider and funding
    provider: Optional[str] = None
    provider_org: Optional[str] = None
    total_allocation: Optional[Decimal] = None
    allocation_currency: str = "EUR"
    min_grant: Optional[Decimal] = None
    max_grant: Optional[Decimal] = None
    cofinancing_percent: Optional[Decimal] = None
    
    # Eligibility
    eligible_applicants: List[str] = Field(default_factory=list)
    eligible_applicants_text: Optional[str] = None
    
    # Categorization
    sector_tags: List[str] = Field(default_factory=list)
    area_tags: List[str] = Field(default_factory=list)
    
    # Conditions
    conditions: Optional[Dict[str, Any]] = None
    evaluation_criteria: Optional[str] = None
    
    # Contact
    contact_person: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_web: Optional[str] = None
    
    # Attachments
    attachments: List[Attachment] = Field(default_factory=list)
    
    # Processing state
    enrichment_status: EnrichmentStatus = EnrichmentStatus.PENDING
    extraction_method: ExtractionMethod = ExtractionMethod.LLM
    extraction_confidence: Optional[float] = None
    extraction_model: Optional[str] = None
    enrichment_run_id: Optional[UUID] = None
    
    # Timestamps
    enrichment_started_at: Optional[datetime] = None
    enrichment_completed_at: Optional[datetime] = None
    
    # Audit
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Raw data
    raw_html: Optional[str] = None
    raw_extraction: Optional[Dict[str, Any]] = None


# ============================================================================
# RUN TRACKING MODELS
# ============================================================================

class DiscoveryRun(BaseModel):
    """Tracking discovery phase runs"""
    id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    sources_processed: int = 0
    links_found: int = 0
    links_classified: int = 0
    links_qualified: int = 0
    status: str = "running"  # running, completed, failed
    error_message: Optional[str] = None


class EnrichmentRun(BaseModel):
    """Tracking enrichment phase runs"""
    id: Optional[UUID] = None
    discovery_run_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    calls_processed: int = 0
    calls_success: int = 0
    calls_failed: int = 0
    calls_manual: int = 0
    status: str = "running"
    error_message: Optional[str] = None
