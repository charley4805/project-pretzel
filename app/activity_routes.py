from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
from app import models, schemas

router = APIRouter()

@router.get(
    "/activities/catalog",
    response_model=List[schemas.ActivityCatalogItem],
)
def get_activity_catalog(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return the global catalog of Activities (for the left-hand list
    in the 'Add Activities' dialog).
    """
    rows = (
        db.query(models.Activity)
        .order_by(models.Activity.is_custom.asc(), models.Activity.name.asc())
        .all()
    )

    return [
        schemas.ActivityCatalogItem(
            id=row.id,
            name=row.name,
            description=row.description,
            is_custom=row.is_custom,
        )
        for row in rows
    ]
