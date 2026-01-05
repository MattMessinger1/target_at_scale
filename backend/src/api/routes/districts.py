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
        await scrape_district(district_id, db)
        return {"message": f"Scraping started for {district.name}"}
    except Exception as e:
        district.scrape_status = "error"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))
