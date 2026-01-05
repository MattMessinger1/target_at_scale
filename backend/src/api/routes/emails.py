"""Email API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime
import csv
import io

from ...db import get_db, Email, District, Contact

router = APIRouter()


class EmailResponse(BaseModel):
    """Email response model."""
    id: int
    district_id: str
    contact_id: Optional[int]
    subject_line: str
    email_body: str
    content_used: Optional[dict]
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    review_notes: Optional[str]
    exported_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class EmailGenerateRequest(BaseModel):
    """Request to generate an email."""
    district_id: str
    contact_id: Optional[int] = None
    custom_instructions: Optional[str] = None


class EmailApproveRequest(BaseModel):
    """Request to approve an email."""
    approved_by: str
    review_notes: Optional[str] = None


@router.get("/", response_model=List[EmailResponse])
async def list_emails(
    district_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List emails with optional filters."""
    query = select(Email)
    
    if district_id:
        query = query.where(Email.district_id == district_id)
    if status:
        query = query.where(Email.status == status)
    
    query = query.order_by(Email.created_at.desc())
    result = await db.execute(query)
    emails = result.scalars().all()
    return emails


@router.get("/{email_id}", response_model=EmailResponse)
async def get_email(email_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific email."""
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


@router.post("/generate", response_model=EmailResponse)
async def generate_email(request: EmailGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate an email for a district using curated content."""
    from ...generator.email import generate_email_for_district
    
    # Verify district exists
    result = await db.execute(select(District).where(District.id == request.district_id))
    district = result.scalar_one_or_none()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    
    # Generate the email
    email = await generate_email_for_district(
        district_id=request.district_id,
        contact_id=request.contact_id,
        custom_instructions=request.custom_instructions,
        db=db
    )
    
    return email


@router.post("/{email_id}/approve", response_model=EmailResponse)
async def approve_email(
    email_id: int,
    request: EmailApproveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Approve an email for export."""
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    email.status = "approved"
    email.approved_by = request.approved_by
    email.approved_at = datetime.utcnow()
    email.review_notes = request.review_notes
    
    await db.commit()
    await db.refresh(email)
    return email


@router.patch("/{email_id}", response_model=EmailResponse)
async def update_email(
    email_id: int,
    subject_line: Optional[str] = None,
    email_body: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Update email content (for manual edits)."""
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    if subject_line:
        email.subject_line = subject_line
    if email_body:
        email.email_body = email_body
    
    await db.commit()
    await db.refresh(email)
    return email


@router.post("/export")
async def export_emails(
    status: str = "approved",
    district_ids: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db)
):
    """Export emails to Account Engagement CSV format."""
    from ...export.salesforce import generate_account_engagement_csv
    
    query = select(Email).where(Email.status == status)
    
    if district_ids:
        query = query.where(Email.district_id.in_(district_ids))
    
    result = await db.execute(query)
    emails = result.scalars().all()
    
    if not emails:
        raise HTTPException(status_code=404, detail="No emails found for export")
    
    # Generate CSV
    csv_content = await generate_account_engagement_csv(emails, db)
    
    # Mark as exported
    batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    for email in emails:
        email.exported_at = datetime.utcnow()
        email.export_batch_id = batch_id
        email.status = "exported"
    await db.commit()
    
    # Return as downloadable file
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=wceps_emails_{batch_id}.csv"
        }
    )


@router.get("/export/preview")
async def preview_export(
    status: str = "approved",
    db: AsyncSession = Depends(get_db)
):
    """Preview what would be exported."""
    query = select(Email).where(Email.status == status)
    result = await db.execute(query)
    emails = result.scalars().all()
    
    preview = []
    for email in emails:
        # Get contact info if available
        contact_info = None
        if email.contact_id:
            contact_result = await db.execute(select(Contact).where(Contact.id == email.contact_id))
            contact = contact_result.scalar_one_or_none()
            if contact:
                contact_info = {
                    "name": contact.full_name,
                    "email": contact.email,
                    "title": contact.title,
                }
        
        # Get district info
        district_result = await db.execute(select(District).where(District.id == email.district_id))
        district = district_result.scalar_one_or_none()
        
        preview.append({
            "email_id": email.id,
            "district_name": district.name if district else email.district_id,
            "contact": contact_info,
            "subject_line": email.subject_line,
            "body_preview": email.email_body[:200] + "..." if len(email.email_body) > 200 else email.email_body,
            "status": email.status,
        })
    
    return {"count": len(preview), "emails": preview}
