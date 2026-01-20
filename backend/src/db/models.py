"""Database models for WCEPS Email Generator."""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Text, DateTime, Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class District(Base):
    """School district information."""
    __tablename__ = "districts"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    state_full: Mapped[str] = mapped_column(String(50), nullable=False)
    website_url: Mapped[str] = mapped_column(String(500), nullable=False)
    student_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    el_student_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    el_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Scraping status
    scrape_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, in_progress, completed, error
    scrape_phase: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # mapping, contacts, research
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Identified needs (extracted from scraping)
    identified_needs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    contacts: Mapped[List["Contact"]] = relationship("Contact", back_populates="district", cascade="all, delete-orphan")
    scraped_content: Mapped[List["ScrapedContent"]] = relationship("ScrapedContent", back_populates="district", cascade="all, delete-orphan")
    emails: Mapped[List["Email"]] = relationship("Email", back_populates="district", cascade="all, delete-orphan")
    snippets: Mapped[List["ExtractedSnippet"]] = relationship("ExtractedSnippet", back_populates="district", cascade="all, delete-orphan")


class Contact(Base):
    """District contact information."""
    __tablename__ = "contacts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[str] = mapped_column(String(50), ForeignKey("districts.id"), nullable=False)
    
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Source tracking
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Verification
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relevance to EL programs
    is_el_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    district: Mapped["District"] = relationship("District", back_populates="contacts")
    emails: Mapped[List["Email"]] = relationship("Email", back_populates="contact")


class ScrapedContent(Base):
    """Content scraped from district websites or researched via Perplexity."""
    __tablename__ = "scraped_content"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[str] = mapped_column(String(50), ForeignKey("districts.id"), nullable=False)
    
    # Content type: funding, compliance, strategic_priority, news, contact_page, url_mapping
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Content details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Source tracking
    source: Mapped[str] = mapped_column(String(50), default="firecrawl")  # firecrawl, perplexity, knowledge_base
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # For human curation
    included_in_email: Mapped[bool] = mapped_column(Boolean, default=False)
    human_weight_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    human_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    district: Mapped["District"] = relationship("District", back_populates="scraped_content")
    scores: Mapped[List["ContentScore"]] = relationship("ContentScore", back_populates="content", cascade="all, delete-orphan")


class ContentScore(Base):
    """Relevance scores for scraped content."""
    __tablename__ = "content_scores"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("scraped_content.id"), nullable=False)
    
    # Individual scores (0-1)
    product_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    state_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    recency_score: Mapped[float] = mapped_column(Float, default=0.0)
    urgency_score: Mapped[float] = mapped_column(Float, default=0.0)
    specificity_score: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Final weighted score
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Matched product (if applicable)
    matched_product: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    content: Mapped["ScrapedContent"] = relationship("ScrapedContent", back_populates="scores")


class Email(Base):
    """Generated emails."""
    __tablename__ = "emails"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[str] = mapped_column(String(50), ForeignKey("districts.id"), nullable=False)
    contact_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("contacts.id"), nullable=True)
    
    # Email content
    subject_line: Mapped[str] = mapped_column(String(200), nullable=False)
    email_body: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Generation context
    content_used: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # IDs of ScrapedContent used
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Status workflow
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft, approved, exported
    
    # Review
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Export tracking
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    export_batch_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    district: Mapped["District"] = relationship("District", back_populates="emails")
    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="emails")


class ExtractedSnippet(Base):
    """Email-ready snippets extracted from raw scraped content."""
    __tablename__ = "extracted_snippets"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[str] = mapped_column(String(50), ForeignKey("districts.id"), nullable=False)
    source_content_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("scraped_content.id"), nullable=True)
    
    # Snippet categorization
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # contact, statistic, priority, funding, compliance, program
    
    # The actual email-ready snippet
    snippet_text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Why this snippet is useful for the email
    relevance_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # AI confidence in extraction quality (0-1)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    
    # User selection for email inclusion
    included_in_email: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Optional: matched WCEPS product this snippet relates to
    matched_product: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Timestamps
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    district: Mapped["District"] = relationship("District", back_populates="snippets")
    source_content: Mapped[Optional["ScrapedContent"]] = relationship("ScrapedContent")


class KnowledgeBaseItem(Base):
    """Processed knowledge base items for searching."""
    __tablename__ = "knowledge_base"
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    
    # Content categorization
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # product, case_study, state_content, testimonial
    subcategory: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., care_coaching, wida_model, florida
    
    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Metadata from original KB
    document_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # For state-specific content
    applicable_states: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # For product content
    product_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Timestamps
    original_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductBrief(Base):
    """Stored, structured product brief used for email generation.

    Briefs are built (offline) from KB materials + optional curated overrides, then
    stored in the database for fast, reliable runtime generation.
    """

    __tablename__ = "product_briefs"
    __table_args__ = (
        UniqueConstraint("product_key", "state_code", name="uq_product_briefs_product_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Canonical product key (e.g., care_coaching)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional two-letter state code variant (e.g., FL). NULL means general brief.
    state_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)

    # JSON blob holding the brief fields (see research/product_briefs.py)
    brief_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # How this brief was produced (auto, override, merged, on_demand)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="auto")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TreasureHookFeedback(Base):
    """Human feedback on treasure hook selection (training signal)."""

    __tablename__ = "treasure_hook_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Context
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    product_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    audiences: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    district_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Decision + reasons
    decision: Mapped[str] = mapped_column(String(12), nullable=False)  # selected|rejected
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1=primary, 2=secondary
    reason_tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # list[str]
    reason_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Hook payload (denormalized for easy export)
    hook_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    link: Mapped[str] = mapped_column(String(800), nullable=False)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eligibility_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why_relevant: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_quality_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class EmailImprovementReview(Base):
    """Human review + edits for a generated email (training signal)."""

    __tablename__ = "email_improvement_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Context
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    product_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    audience: Mapped[str] = mapped_column(String(200), nullable=False)
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    district_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    primary_hook_link: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    secondary_hook_link: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)

    # Original vs edited text
    original_subject_line: Mapped[str] = mapped_column(String(400), nullable=False)
    original_email_body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_subject_line: Mapped[str] = mapped_column(String(400), nullable=False)
    edited_email_body: Mapped[str] = mapped_column(Text, nullable=False)

    # Rubric: store as JSON for flexibility
    rubric: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    
    # Evidence chunks used in generating this email (for tracking chunk quality)
    evidence_chunks_used: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # List of chunk IDs


class GoldenEmail(Base):
    """Human-approved emails used as few-shot examples for self-improving generation.
    
    Emails qualify as 'golden' when:
    - User edited the email (corrections = good examples)
    - All rubric scores >= 4 (high quality)
    
    These are retrieved at generation time to provide few-shot examples.
    """
    
    __tablename__ = "golden_emails"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Context for retrieval matching
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    product_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    audience: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # The approved email content
    subject_line: Mapped[str] = mapped_column(String(400), nullable=False)
    email_body: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Why it's golden
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # "edited" | "rubric_qualified"
    rubric_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {subject_line: 5, tone: 4, ...}
    
    # Additional context for smarter retrieval
    hook_types_used: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # ["state_funding", "compliance"]
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Custom purpose prompt (if the email was generated with one)
    purpose_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Reference back to the review that created this
    review_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class NegativeEmailExample(Base):
    """Emails with low rubric scores (1-2) used as negative examples in prompts.
    
    Emails qualify as 'negative' when any rubric score is 1 or 2.
    These are shown in prompts as "avoid this pattern" examples.
    """
    
    __tablename__ = "negative_email_examples"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Context for retrieval matching
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    product_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    audience: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # The email content to avoid
    subject_line: Mapped[str] = mapped_column(String(400), nullable=False)
    email_body: Mapped[str] = mapped_column(Text, nullable=False)
    
    # What was wrong (which categories scored low)
    low_score_categories: Mapped[list] = mapped_column(JSON, nullable=False)  # ["hook_usage", "cta"]
    rubric_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {subject_line: 3, hook_usage: 1, ...}
    
    # Weight for prioritizing examples (2.0 for score=1, 1.0 for score=2)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    
    # Additional context
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    purpose_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Reference back to the review that created this
    review_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ChunkFeedback(Base):
    """Feedback on KB chunks used in emails (for manual review).
    
    When an email has low product_relevance score, the chunks used
    can be flagged here for manual review and potential YAML kb_curation updates.
    """
    
    __tablename__ = "chunk_feedback"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Which chunk
    chunk_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_kb_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    
    # Context
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    
    # Feedback
    flag_reason: Mapped[str] = mapped_column(String(50), nullable=False)  # "low_relevance", "outdated", "incorrect"
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Reference to the review that triggered this flag
    review_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Resolution status
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DeepResearchCache(Base):
    """Cache for OpenAI Deep Research results (14-day TTL).
    
    Deep Research takes 5-30 minutes and is expensive, so we cache results
    by (state_code, product_key) for reuse.
    """
    
    __tablename__ = "deep_research_cache"
    __table_args__ = (
        UniqueConstraint("state_code", "product_key", "research_type", name="uq_deep_research_cache_key"),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Cache key components
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    research_type: Mapped[str] = mapped_column(String(50), nullable=False, default="funding_compliance")
    
    # Optional district for district-specific deep dives
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Research results (JSON blob)
    results_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    
    # Full prep response (evidence_pack + hooks) for instant cache hits
    full_prep_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # OpenAI response metadata
    openai_response_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Status: pending, in_progress, completed, failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Archive flag for hiding old data without deletion
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Timestamps for cache invalidation (30-day TTL)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DistrictResearchCache(Base):
    """Cache for district-level research results (30-day TTL).
    
    District research surveys top 30 districts in a state by EL population
    for incremental funding/compliance opportunities beyond state-level findings.
    """
    
    __tablename__ = "district_research_cache"
    __table_args__ = (
        UniqueConstraint("state_code", "product_key", name="uq_district_research_cache_key"),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Cache key components
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Districts surveyed (up to 30)
    districts_surveyed: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Results: list of district hooks (each tagged with district_name)
    results_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    
    # Filtered items (for transparency display)
    filtered_items_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # OpenAI task tracking (for resumability)
    openai_response_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Status: pending, in_progress, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Archive flag for hiding old data without deletion
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Timestamps for cache invalidation (30-day TTL)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResearchTask(Base):
    """Track research tasks for polling-based progress.
    
    This enables robust research that survives browser tab sleep,
    network hiccups, and page refreshes. Results are auto-saved to SavedEmailRun
    on completion.
    """
    __tablename__ = "research_tasks"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # UUID
    
    # Who started this task (for team attribution)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Request context
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    product_key: Mapped[str] = mapped_column(String(100), nullable=False)
    product_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    state_full: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    audiences: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    include_district_research: Mapped[bool] = mapped_column(Boolean, default=False)
    include_conference_research: Mapped[bool] = mapped_column(Boolean, default=False)
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    district_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Phase: 'state', 'district', or 'conferences'
    phase: Mapped[str] = mapped_column(String(20), default='state')
    
    # Status: queued, in_progress, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(20), default='queued')
    
    # Progress (0-100)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    
    # Human-readable status message
    message: Mapped[str] = mapped_column(Text, default='')
    
    # Results stored as JSON (when completed)
    evidence_pack_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    treasure_hooks_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    filtered_requirements_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    district_research_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    conferences_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Error details (when failed)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Auto-save reference (when research completes, it's auto-saved here)
    saved_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Cleanup: auto-delete old tasks after 1 hour
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BatchJob(Base):
    """Batch research jobs across multiple states."""
    __tablename__ = "batch_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Job configuration
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    states: Mapped[list] = mapped_column(JSON, nullable=False)  # List of {code, name} objects
    audiences: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    
    # Research options (persisted for resume after restart)
    include_district_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    include_conference_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Progress tracking
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, running, completed, failed, cancelled
    total_states: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_states: Mapped[int] = mapped_column(Integer, default=0)
    failed_states: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    runs: Mapped[List["SavedEmailRun"]] = relationship("SavedEmailRun", back_populates="batch_job")


class SavedEmailRun(Base):
    """Saved email/research runs for later retrieval."""
    __tablename__ = "saved_email_runs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Run type: "research" (pre-email) or "email" (full pipeline)
    run_type: Mapped[str] = mapped_column(String(20), default="email")
    
    # User-provided name (optional)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Who created this run (for team attribution)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Generation context
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    state_full: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    audiences: Mapped[list] = mapped_column(JSON, nullable=False)
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Research options (for re-research to remember original settings)
    include_district_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    include_conference_research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Custom purpose prompt (for purpose-driven emails)
    purpose_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Selected cached hooks (for purpose-driven emails with cached research)
    selected_cached_hook_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Full pipeline response (variants, evidence_pack, hooks)
    # For run_type="research": contains evidence_pack and hooks only
    # For run_type="email": contains full pipeline response with variants
    pipeline_response: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # Selected hooks context
    selected_hook_links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    primary_hook_link: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    hook_reason_tags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hook_reason_notes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    
    # Batch job reference (if part of a batch)
    batch_job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batch_jobs.id"), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    batch_job: Mapped[Optional["BatchJob"]] = relationship("BatchJob", back_populates="runs")


class EmailTask(Base):
    """Track email generation tasks for polling and resume after server restart.
    
    This enables:
    1. Multiple concurrent email generations without session conflicts
    2. Progress polling via /pipeline/run/status?task_id=X
    3. Automatic resume if server restarts mid-generation
    4. Auto-save to SavedEmailRun on completion
    """
    __tablename__ = "email_tasks"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # UUID
    
    # Who started this task (for team attribution)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Request context
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    state_full: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    audiences: Mapped[list] = mapped_column(JSON, nullable=False)
    district_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    district_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    purpose_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Selected hooks for generation
    selected_hook_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selected_cached_hooks: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Progress tracking
    status: Mapped[str] = mapped_column(String(20), default='queued')  # queued, in_progress, completed, failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    message: Mapped[str] = mapped_column(Text, default='')  # Human-readable status message
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # evidence_pack, treasure_hunter, email_writing, validation
    
    # OpenAI task tracking (for resume after restart)
    openai_response_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # resp_xxx ID
    openai_audience: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Which audience is being generated
    
    # Intermediate state (checkpoints for resume)
    evidence_pack_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    treasure_hooks_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selected_hook_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    completed_variants_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    
    # Result / Error
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Auto-cleanup: tasks expire after 2 hours
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Link to auto-saved result
    saved_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ApiUsageLog(Base):
    """Log of API usage for cost tracking.
    
    Records actual token usage and costs for each API call,
    enabling cost monitoring and comparison with estimates.
    """
    __tablename__ = "api_usage_log"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Operation context
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # state_research, district_research, email_default, etc.
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)  # o3-deep-research, gpt-5.2, etc.
    
    # Token counts
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    web_search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Cost tracking
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    
    # Context for grouping/filtering
    state_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    batch_job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Additional metadata (JSON blob for flexibility)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)