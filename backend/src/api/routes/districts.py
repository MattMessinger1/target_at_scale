"""District API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from ...db import get_db, District

router = APIRouter()


class DistrictResponse(BaseModel):
    """District response model."""
    id: str
    name: str
    state: str
    state_full: str
    website_url: str
    student_count: Optional[int]
    el_student_count: Optional[int]
    el_percentage: Optional[float]
    scrape_status: str
    scrape_phase: Optional[str]
    last_scraped_at: Optional[datetime]
    identified_needs: Optional[dict]
    
    class Config:
        from_attributes = True


class DistrictCreate(BaseModel):
    """District creation model."""
    id: str
    name: str
    state: str
    state_full: str
    website_url: str
    student_count: Optional[int] = None
    el_student_count: Optional[int] = None
    el_percentage: Optional[float] = None


@router.get("/", response_model=List[DistrictResponse])
async def list_districts(db: AsyncSession = Depends(get_db)):
    """List all districts."""
    result = await db.execute(select(District).order_by(District.state, District.name))
    districts = result.scalars().all()
    return districts


@router.get("/{district_id}", response_model=DistrictResponse)
async def get_district(district_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific district."""
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    return district


@router.post("/", response_model=DistrictResponse)
async def create_district(district: DistrictCreate, db: AsyncSession = Depends(get_db)):
    """Create a new district."""
    db_district = District(**district.model_dump())
    db.add(db_district)
    await db.commit()
    await db.refresh(db_district)
    return db_district


@router.post("/load-pilot")
async def load_pilot_districts(db: AsyncSession = Depends(get_db)):
    """Load pilot districts from JSON file."""
    import json
    from pathlib import Path
    
    pilot_file = Path(__file__).parent.parent.parent.parent.parent / "data" / "pilot_districts.json"
    
    if not pilot_file.exists():
        raise HTTPException(status_code=404, detail="Pilot districts file not found")
    
    with open(pilot_file) as f:
        pilot_data = json.load(f)
    
    created = []
    for d in pilot_data:
        # Check if already exists
        result = await db.execute(select(District).where(District.id == d["id"]))
        existing = result.scalar_one_or_none()
        
        if existing:
            continue
        
        district = District(
            id=d["id"],
            name=d["name"],
            state=d["state"],
            state_full=d["state_full"],
            website_url=d["website_url"],
            student_count=d.get("student_count"),
            el_student_count=d.get("el_student_count"),
            el_percentage=d.get("el_percentage"),
        )
        db.add(district)
        created.append(d["name"])
    
    await db.commit()
    
    return {"message": f"Loaded {len(created)} districts", "districts": created}


@router.post("/{district_id}/scrape")
async def trigger_scrape(district_id: str, db: AsyncSession = Depends(get_db)):
    """Trigger scraping for a district."""
    from ...scraper.firecrawl import scrape_district
    
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    
    # Update status
    district.scrape_status = "in_progress"
    district.scrape_phase = "mapping"
    await db.commit()
    
    # Start scraping (this would typically be a background task)
    try:
        result = await scrape_district(district_id, db)
        return {"message": f"Scraping completed for {district.name}", "result": result}
    except Exception as e:
        district.scrape_status = "error"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{district_id}/reset")
async def reset_district(district_id: str, db: AsyncSession = Depends(get_db)):
    """Reset a district's scrape status and clear scraped content."""
    from ...db import ScrapedContent, Contact
    
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    
    # Delete all scraped content for this district
    await db.execute(
        select(ScrapedContent).where(ScrapedContent.district_id == district_id)
    )
    content_result = await db.execute(
        select(ScrapedContent).where(ScrapedContent.district_id == district_id)
    )
    for content in content_result.scalars().all():
        await db.delete(content)
    
    # Delete all contacts for this district
    contact_result = await db.execute(
        select(Contact).where(Contact.district_id == district_id)
    )
    for contact in contact_result.scalars().all():
        await db.delete(contact)
    
    # Reset district status
    district.scrape_status = "pending"
    district.scrape_phase = None
    district.last_scraped_at = None
    district.identified_needs = None
    
    await db.commit()
    
    return {"message": f"Reset {district.name} to pending status"}


@router.post("/reset-all-pilot")
async def reset_all_pilot_districts(db: AsyncSession = Depends(get_db)):
    """Reset all pilot districts to pending status."""
    from ...db import ScrapedContent, Contact
    
    # Get all districts
    result = await db.execute(select(District))
    districts = result.scalars().all()
    
    reset_count = 0
    for district in districts:
        # Delete scraped content
        content_result = await db.execute(
            select(ScrapedContent).where(ScrapedContent.district_id == district.id)
        )
        for content in content_result.scalars().all():
            await db.delete(content)
        
        # Delete contacts
        contact_result = await db.execute(
            select(Contact).where(Contact.district_id == district.id)
        )
        for contact in contact_result.scalars().all():
            await db.delete(contact)
        
        # Reset status
        district.scrape_status = "pending"
        district.scrape_phase = None
        district.last_scraped_at = None
        district.identified_needs = None
        reset_count += 1
    
    await db.commit()
    
    return {"message": f"Reset {reset_count} districts to pending status"}
