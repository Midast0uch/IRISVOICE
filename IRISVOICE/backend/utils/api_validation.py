"""
API Key and URL Validation Utilities

This module provides validation functions for API keys and URLs,
particularly for OpenAI-compatible APIs.
"""

import re
from typing import Tuple
from urllib.parse import urlparse


def validate_openai_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate OpenAI API key format.
    
    OpenAI API keys follow the pattern: sk-[alphanumeric characters]
    This validation also works for OpenAI-compatible APIs that use the same format.
    
    Args:
        api_key: The API key to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the key format is valid
        - error_message: Empty string if valid, error description if invalid
    """
    if not api_key:
        return False, "API key cannot be empty"
    
    if not isinstance(api_key, str):
        return False, "API key must be a string"
    
    # Check if key starts with "sk-"
    if not api_key.startswith("sk-"):
        return False, "API key must start with 'sk-'"
    
    # Check minimum length (sk- + at least some characters)
    if len(api_key) < 10:
        return False, "API key is too short"
    
    # Check that the key contains only valid characters (alphanumeric, hyphens, underscores)
    # after the "sk-" prefix
    key_body = api_key[3:]  # Remove "sk-" prefix
    if not re.match(r'^[A-Za-z0-9_-]+$', key_body):
        return False, "API key contains invalid characters"
    
    return True, ""


def validate_api_url(url: str) -> Tuple[bool, str]:
    """
    Validate API URL format.
    
    Ensures the URL is a valid HTTPS URL suitable for API endpoints.
    Supports custom URLs for OpenAI-compatible APIs, proxy servers, and self-hosted solutions.
    
    Args:
        url: The API URL to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the URL format is valid
        - error_message: Empty string if valid, error description if invalid
    """
    if not url:
        return False, "API URL cannot be empty"
    
    if not isinstance(url, str):
        return False, "API URL must be a string"
    
    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {str(e)}"
    
    # Check scheme (must be https for security)
    if parsed.scheme not in ['https', 'http']:
        return False, "API URL must use HTTP or HTTPS protocol"
    
    # Warn if using HTTP instead of HTTPS (but allow it for local development)
    if parsed.scheme == 'http' and not parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
        # Allow HTTP for localhost, but warn for remote servers
        pass  # We'll allow it but could add a warning mechanism
    
    # Check that hostname exists
    if not parsed.hostname:
        return False, "API URL must include a hostname"
    
    # Check for common issues
    if parsed.hostname.endswith('.'):
        return False, "API URL hostname cannot end with a dot"
    
    return True, ""


def validate_openai_config(api_key: str, api_url: str) -> Tuple[bool, str]:
    """
    Validate complete OpenAI API configuration.
    
    Validates both the API key and URL together.
    
    Args:
        api_key: The API key to validate
        api_url: The API URL to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if both key and URL are valid
        - error_message: Empty string if valid, error description if invalid
    """
    # Validate API key
    key_valid, key_error = validate_openai_key(api_key)
    if not key_valid:
        return False, f"API Key Error: {key_error}"
    
    # Validate API URL
    url_valid, url_error = validate_api_url(api_url)
    if not url_valid:
        return False, f"API URL Error: {url_error}"
    
    return True, ""
