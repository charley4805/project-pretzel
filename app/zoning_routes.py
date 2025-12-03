from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ZoningLookupRequest(BaseModel):
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str


class ZoningLookupResponse(BaseModel):
    zoning_code: str
    jurisdiction: str
    likely_permits: List[str]
    note: Optional[str] = None


@router.post("/zoning/lookup", response_model=ZoningLookupResponse)
def zoning_lookup(payload: ZoningLookupRequest) -> ZoningLookupResponse:
    """
    Stubbed zoning lookup.
    Later, you can plug in a real zoning / permit API here
    (by city/state/zip, county GIS, or a commercial zoning service).
    """

    city = payload.city.strip().lower()
    state = payload.state.strip().upper()

    # 🧠 Example: special-case Woodstock, GA with realistic-ish defaults
    if city == "woodstock" and state == "GA":
        return ZoningLookupResponse(
            zoning_code="R-1",
            jurisdiction="Woodstock, GA",
            likely_permits=[
                "Building Permit",
                "Electrical Permit",
                "Mechanical / HVAC Permit",
            ],
            note=(
                "Typical low-density single-family residential zoning. "
                "Always confirm with the local jurisdiction before starting work."
            ),
        )

    # Generic fallback for anywhere else
    return ZoningLookupResponse(
        zoning_code="RES",
        jurisdiction=f"{payload.city.strip()}, {state}",
        likely_permits=["Building Permit", "Electrical Permit"],
        note=(
            "Generic residential assumption based on address. "
            "Replace this logic once you connect a real zoning API."
        ),
    )
