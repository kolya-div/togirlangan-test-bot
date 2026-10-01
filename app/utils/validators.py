"""
Input validation utilities for security.

This module provides validation functions for user inputs to prevent
common security issues like injection attacks, malformed data, etc.
"""

import re
import logging
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


# SQL injection patterns
SQL_INJECTION_PATTERNS = [
    r'\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC|ALTER|CREATE|TRUNCATE)\b',
    r'--\s*$',
    r'/\*.*\*/',
    r';\s*(SELECT|INSERT|UPDATE|DELETE|DROP)',
    r'\bor\s+1\s*=\s*1\b',
    r'\band\s+1\s*=\s*1\b',
]

# XSS patterns
XSS_PATTERNS = [
    r'<script[^>]*>.*?</script>',
    r'on\w+\s*=',
    r'javascript:',
    r'vbscript:',
    r'data:text/html',
]

# File path injection patterns
PATH_TRAVERSAL_PATTERNS = [
    r'\.\./.*',
    r'\.\.\\.*',
    r'\.\.\/.*',
    r'\.%2e%2e%2f',
    r'\.%2e%2e%5c',
]


def validate_string_input(
    value: str,
    max_length: int = 1000,
    min_length: int = 0,
    allow_html: bool = False,
    field_name: str = "input"
) -> str:
    """
    Validate string input for security.
    
    Args:
        value: Input string to validate
        max_length: Maximum allowed length
        min_length: Minimum allowed length
        allow_html: Whether HTML content is allowed
        field_name: Name of the field for error messages
    
    Returns:
        Validated and sanitized string
    
    Raises:
        ValueError: If validation fails
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    
    # Length validation
    if len(value) < min_length:
        raise ValueError(f"{field_name} must be at least {min_length} characters")
    
    if len(value) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")
    
    # HTML validation
    if not allow_html:
        if '<' in value or '>' in value:
            logger.warning(f"HTML content detected in {field_name}")
            # Strip HTML tags
            value = re.sub(r'<[^>]+>', '', value)
    
    # XSS prevention
    for pattern in XSS_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            logger.warning(f"Potential XSS attempt detected in {field_name}")
            raise ValueError(f"Invalid content in {field_name}")
    
    return value.strip()


def validate_file_path(file_path: str, allowed_extensions: set[str]) -> Path:
    """
    Validate file path for security (prevent path traversal).
    
    Args:
        file_path: File path to validate
        allowed_extensions: Set of allowed file extensions
    
    Returns:
        Validated Path object
    
    Raises:
        ValueError: If validation fails
    """
    # Check for path traversal
    for pattern in PATH_TRAVERSAL_PATTERNS:
        if re.search(pattern, file_path, re.IGNORECASE):
            logger.warning(f"Path traversal attempt detected: {file_path}")
            raise ValueError("Invalid file path")
    
    path = Path(file_path)
    
    # Check extension
    if path.suffix.lower() not in allowed_extensions:
        raise ValueError(f"File extension {path.suffix} not allowed")
    
    # Check for absolute paths (should be relative to allowed directory)
    if path.is_absolute():
        raise ValueError("Absolute file paths not allowed")
    
    return path


def validate_telegram_id(telegram_id: Any) -> int:
    """
    Validate Telegram user ID.
    
    Args:
        telegram_id: Telegram ID to validate
    
    Returns:
        Validated integer Telegram ID
    
    Raises:
        ValueError: If validation fails
    """
    try:
        telegram_id = int(telegram_id)
    except (ValueError, TypeError):
        raise ValueError("Telegram ID must be an integer")
    
    if telegram_id <= 0:
        raise ValueError("Telegram ID must be positive")
    
    # Telegram user ID'lari 52 bitgacha bo'ladi (Bot API hujjati). Oldingi
    # 2**31-1 chegarasi yangi akkauntlarni (ID 8 000 000 000+) rad etardi —
    # ular /api/init da 400 olib, testni umuman boshlay olmasdi.
    if telegram_id > 2**52:
        raise ValueError("Telegram ID exceeds maximum value")
    
    return telegram_id


def validate_test_score(score: Any, max_score: int = 100) -> int:
    """
    Validate test score.
    
    Args:
        score: Score to validate
        max_score: Maximum allowed score
    
    Returns:
        Validated integer score
    
    Raises:
        ValueError: If validation fails
    """
    try:
        score = int(score)
    except (ValueError, TypeError):
        raise ValueError("Score must be an integer")
    
    if score < 0:
        raise ValueError("Score cannot be negative")
    
    if score > max_score:
        raise ValueError(f"Score cannot exceed {max_score}")
    
    return score


def sanitize_transcript(transcript: str) -> str:
    """
    Sanitize transcript text for safe storage and display.
    
    Args:
        transcript: Raw transcript text
    
    Returns:
        Sanitized transcript
    """
    if not transcript:
        return ""
    
    # Remove excessive whitespace
    transcript = re.sub(r'\s+', ' ', transcript)
    
    # Remove control characters except newlines and tabs
    transcript = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', transcript)
    
    # Limit length
    max_length = 10000
    if len(transcript) > max_length:
        logger.warning(f"Transcript truncated from {len(transcript)} to {max_length}")
        transcript = transcript[:max_length]
    
    return transcript.strip()


def validate_audio_file_size(file_size: int, max_size_mb: int = 50) -> bool:
    """
    Validate audio file size.
    
    Args:
        file_size: File size in bytes
        max_size_mb: Maximum allowed size in megabytes
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If validation fails
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if file_size <= 0:
        raise ValueError("Audio file is empty")
    
    if file_size > max_size_bytes:
        raise ValueError(f"Audio file exceeds maximum size of {max_size_mb}MB")
    
    return True


def validate_email(email: str) -> str:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        Validated email
    
    Raises:
        ValueError: If validation fails
    """
    if not email:
        raise ValueError("Email cannot be empty")
    
    # Basic email validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise ValueError("Invalid email format")
    
    return email.lower().strip()


def validate_phone_number(phone: str) -> str:
    """
    Validate phone number format.
    
    Args:
        phone: Phone number to validate
    
    Returns:
        Validated phone number
    
    Raises:
        ValueError: If validation fails
    """
    if not phone:
        raise ValueError("Phone number cannot be empty")
    
    # Remove all non-digit characters
    phone = re.sub(r'[^\d+]', '', phone)
    
    # Basic validation (10-15 digits)
    if len(phone) < 10 or len(phone) > 15:
        raise ValueError("Phone number must be 10-15 digits")
    
    return phone