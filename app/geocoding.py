# app/geocoding.py
from typing import Optional, Tuple
import httpx

NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_address(
    *,
    city: Optional[str],
    state: Optional[str],
    postal_code: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Use OpenStreetMap Nominatim to convert city/state/postal_code
    into latitude/longitude. Free, no API key required.

    Returns (lat, lon) or (None, None) if not found.
    """
    if not city or not state:
        return None, None

    # Build a simple query string
    query = f"{city}, {state}"
    if postal_code:
        query += f" {postal_code}"

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            NOMINATIM_BASE_URL,
            params=params,
            headers={"User-Agent": "project-pretzel/1.0 (geocoding)"},
        )

    if resp.status_code != 200:
        return None, None

    data = resp.json()
    if not data:
        return None, None

    try:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        return lat, lon
    except (KeyError, ValueError, IndexError):
        return None, None
