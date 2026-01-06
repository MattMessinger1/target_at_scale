"""Database models for WCEPS Email Generator."""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Text, DateTime, Boolean, ForeignKey, JSON
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
