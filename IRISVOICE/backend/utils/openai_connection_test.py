"""
OpenAI API connection testing utilities.
"""
import asyncio
import aiohttp
from typing import Tuple


async def test_openai_connection(api_key: str, api_url: str = "https://api.openai.com/v1") -> Tuple[bool, str]:
    """
    Test OpenAI API connection with the provided credentials.
    
    Args:
        api_key: The OpenAI API key to test
        api_url: The API endpoint URL (default: https://api.openai.com/v1)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    if not api_key:
        return False, "API key is required"
    
    if not api_url:
        api_url = "https://api.openai.com/v1"
    
    # Ensure URL doesn't end with slash
    api_url = api_url.rstrip('/')
    
    # Use the models endpoint for a lightweight test
    test_url = f"{api_url}/models"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Check if we got a valid response with models
                    if "data" in data and isinstance(data["data"], list):
                        model_count = len(data["data"])
                        return True, f"Connection successful! Found {model_count} available models."
                    else:
                        return True, "Connection successful!"
                elif response.status == 401:
                    return False, "Invalid API key. Please check your credentials."
                elif response.status == 403:
                    return False, "Access forbidden. Your API key may not have the required permissions."
                elif response.status == 429:
                    return False, "Rate limit exceeded. Please try again later."
                elif response.status == 404:
                    return False, f"API endpoint not found. Please check the URL: {api_url}"
                else:
                    error_text = await response.text()
                    return False, f"Connection failed with status {response.status}: {error_text[:100]}"
    
    except aiohttp.ClientConnectorError as e:
        return False, f"Connection error: Unable to reach {api_url}. Please check the URL and your internet connection."
    except asyncio.TimeoutError:
        return False, f"Connection timeout: The server at {api_url} did not respond in time."
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"
