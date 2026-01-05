"""Salesforce Account Engagement CSV export.

This module generates CSV files in the format required for
Salesforce Account Engagement (formerly Pardot) import.
"""
import csv
import io
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import Email, Contact, District


# Account Engagement CSV columns
ACCOUNT_ENGAGEMENT_COLUMNS = [
    "Email",
    "First Name",
    "Last Name",
    "Title",
    "Company",
    "Salutation",
    "Email Opt Out",
    "Campaign",
    "Custom_Subject",
    "Custom_Body",
    "State",
    "District_ID",
    "Generated_At",
]


def generate_salutation(first_name: Optional[str], title: Optional[str]) -> str:
    """Generate appropriate salutation.
    
    Args:
        first_name: Contact's first name
        title: Contact's job title
    
    Returns:
        Appropriate salutation (Mr., Ms., Dr., or empty)
    """
    if not title:
        return ""
    
    title_lower = title.lower()
    
    # Check for Dr. titles
    if any(term in title_lower for term in ["doctor", "dr.", "phd", "ed.d"]):
        return "Dr."
    
    # Default to no salutation (safer than guessing gender)
    return ""


def clean_text_for_csv(text: str) -> str:
    """Clean text for CSV export.
    
    - Remove any characters that could break CSV parsing
    - Normalize line breaks
    - Escape quotes
    """
    if not text:
        return ""
    
    # Normalize line breaks to single format
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Remove any null characters
    text = text.replace("\x00", "")
    
    # The csv module handles quote escaping, but we ensure consistency
    return text.strip()


async def get_email_export_data(
    email: Email,
    db: AsyncSession
) -> Dict[str, Any]:
    """Get all data needed for exporting an email.
    
    Args:
        email: Email object to export
        db: Database session
    
    Returns:
        Dict with all export fields
    """
    # Get district
    result = await db.execute(
        select(District).where(District.id == email.district_id)
    )
    district = result.scalar_one_or_none()
    
    # Get contact if linked
    contact = None
    if email.contact_id:
        result = await db.execute(
            select(Contact).where(Contact.id == email.contact_id)
        )
        contact = result.scalar_one_or_none()
    
    # Build export data
    data = {
        "Email": contact.email if contact else "",
        "First Name": contact.first_name if contact else "",
        "Last Name": contact.last_name if contact else "",
        "Title": contact.title if contact else "",
        "Company": district.name if district else "",
        "Salutation": generate_salutation(
            contact.first_name if contact else None,
            contact.title if contact else None
        ),
        "Email Opt Out": "FALSE",
        "Campaign": f"WCEPS_Pilot_{datetime.utcnow().strftime('%Y%m')}",
        "Custom_Subject": clean_text_for_csv(email.subject_line),
        "Custom_Body": clean_text_for_csv(email.email_body),
        "State": district.state if district else "",
        "District_ID": email.district_id,
        "Generated_At": email.created_at.isoformat() if email.created_at else "",
    }
    
    return data


async def generate_account_engagement_csv(
    emails: List[Email],
    db: AsyncSession
) -> str:
    """Generate CSV content for Account Engagement import.
    
    Args:
        emails: List of Email objects to export
        db: Database session
    
    Returns:
        CSV content as string
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ACCOUNT_ENGAGEMENT_COLUMNS)
    
    writer.writeheader()
    
    for email in emails:
        data = await get_email_export_data(email, db)
        writer.writerow(data)
    
    return output.getvalue()


async def generate_export_preview(
    emails: List[Email],
    db: AsyncSession
) -> List[Dict[str, Any]]:
    """Generate preview of what will be exported.
    
    Args:
        emails: List of emails to preview
        db: Database session
    
    Returns:
        List of preview dictionaries
    """
    previews = []
    
    for email in emails:
        data = await get_email_export_data(email, db)
        
        previews.append({
            "email_id": email.id,
            "recipient": {
                "email": data["Email"],
                "name": f"{data['First Name']} {data['Last Name']}".strip() or "No contact",
                "title": data["Title"],
                "company": data["Company"],
            },
            "email": {
                "subject": data["Custom_Subject"],
                "body_preview": data["Custom_Body"][:200] + "..." if len(data["Custom_Body"]) > 200 else data["Custom_Body"],
            },
            "campaign": data["Campaign"],
            "state": data["State"],
        })
    
    return previews


def validate_export_data(data: Dict[str, Any]) -> List[str]:
    """Validate export data for completeness.
    
    Args:
        data: Export data dictionary
    
    Returns:
        List of validation warnings (empty if all good)
    """
    warnings = []
    
    if not data.get("Email"):
        warnings.append("Missing recipient email address")
    
    if not data.get("First Name") and not data.get("Last Name"):
        warnings.append("Missing recipient name")
    
    if not data.get("Company"):
        warnings.append("Missing company/district name")
    
    if not data.get("Custom_Subject"):
        warnings.append("Missing email subject line")
    
    if not data.get("Custom_Body"):
        warnings.append("Missing email body")
    elif len(data.get("Custom_Body", "")) < 100:
        warnings.append("Email body is very short (< 100 characters)")
    
    return warnings


async def export_with_validation(
    emails: List[Email],
    db: AsyncSession
) -> Dict[str, Any]:
    """Export emails with validation report.
    
    Args:
        emails: List of emails to export
        db: Database session
    
    Returns:
        Dict with csv_content and validation results
    """
    results = {
        "total_emails": len(emails),
        "valid_emails": 0,
        "warnings": [],
        "csv_content": None,
    }
    
    valid_emails = []
    
    for email in emails:
        data = await get_email_export_data(email, db)
        warnings = validate_export_data(data)
        
        if warnings:
            results["warnings"].append({
                "email_id": email.id,
                "district": data.get("Company", "Unknown"),
                "issues": warnings,
            })
        
        # Include emails that at least have a body (even if missing contact)
        if data.get("Custom_Body"):
            valid_emails.append(email)
            results["valid_emails"] += 1
    
    if valid_emails:
        results["csv_content"] = await generate_account_engagement_csv(valid_emails, db)
    
    return results
