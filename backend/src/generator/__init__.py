"""Generator module for email generation."""
from .email import (
    generate_email_for_district,
    regenerate_email,
    generate_email_content,
    build_email_context,
    STYLE_GUIDE,
)

__all__ = [
    "generate_email_for_district",
    "regenerate_email",
    "generate_email_content",
    "build_email_context",
    "STYLE_GUIDE",
]
