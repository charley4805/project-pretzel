# app/weather_routes.py
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class WeatherResponse(BaseModel):
    temp: float
    condition: str
    description: str
    icon: Optional[str] = None
    feels_like: Optional[float] = None
    updated_at: Optional[str] = None


def map_weather_code(code: int) -> tuple[str, str]:
    if code == 0:
        return ("Clear", "Clear sky")
    if code == 1:
        return ("Mostly Clear", "Mainly clear")
    if code == 2:
        return ("Partly Cloudy", "Partly cloudy")
    if code == 3:
        return ("Cloudy", "Overcast")

    if code in (45, 48):
        return ("Fog", "Fog or depositing rime fog")
    if code in (51, 53, 55):
        return ("Drizzle", "Light to heavy drizzle")
    if code in (61, 63, 65):
        return ("Rain", "Light to heavy rain")
    if code in (66, 67):
        return ("Freezing Rain", "Freezing rain")
    if code in (71, 73, 75, 77):
        return ("Snow", "Snowfall or snow grains")
    if code in (80, 81, 82):
        return ("Showers", "Rain showers")
    if code in (85, 86):
        return ("Snow Showers", "Snow showers")
    if code == 95:
        return ("Thunderstorm", "Thunderstorm")
    if code in (96, 99):
        return ("Thunderstorm", "Thunderstorm with hail")

    return ("Unknown", "Unknown conditions")


@router.get("/weather", response_model=WeatherResponse)
async def get_weather(
    lat: float = Query(...),
    lon: float = Query(...),
    units: str = Query("imperial"),
):
    """
    Weather endpoint (backend side).

    Final URL (after we include with prefix="/api"):
    /api/weather?lat=...&lon=...&units=imperial
    """
    temp_unit = "fahrenheit" if units == "imperial" else "celsius"

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "temperature_unit": temp_unit,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Weather service error: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    current = data.get("current_weather")
    if not current:
        raise HTTPException(status_code=502, detail="Weather data unavailable")

    code = int(current.get("weathercode", -1))
    condition, description = map_weather_code(code)

    return WeatherResponse(
        temp=current.get("temperature"),
        condition=condition,
        description=description,
        icon=None,
        feels_like=None,
        updated_at=current.get("time"),
    )
