# app/project_intake_routes.py

from uuid import UUID
import json
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Project, ProjectDocument
from app.schemas import ProjectIntakeCreate  # defined in schemas.py

# 🔹 All routes in this file will be prefixed with /projects
# Final paths (with api.py prefix) look like:
#   /api/projects/{project_id}/intake
router = APIRouter(prefix="/projects", tags=["project-intake"])


# ---------- RESPONSE / REQUEST MODELS ----------

class ProjectIntakeRead(BaseModel):
    project_id: UUID
    document_id: UUID
    title: str
    content: dict
    created_at: datetime


class ProjectIntakePatch(BaseModel):
    """
    Partial update payload.

    Example:
    {
      "patch": {
        "project_name_final": "New name",
        "notes": "Add HOA constraint",
        "address": { "city": "Woodstock" }
      }
    }
    """
    patch: Dict[str, Any]


# ---------- HELPERS ----------

def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `patch` into `base`.
    - If value is a dict in both, merge recursively.
    - Otherwise, overwrite base[key] with patch[key].
    """
    for key, value in patch.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ---------- ROUTES ----------

@router.post("/{project_id}/intake")
def save_project_intake(
    project_id: UUID,
    payload: ProjectIntakeCreate,
    db: Session = Depends(get_db),
):
    """
    Save a single JSON "Project Intake" document for this project.
    This is what will later be fed into the project's RAG.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Single JSON document for RAG
    content_str = json.dumps(payload.model_dump(), indent=2)

    doc = ProjectDocument(
        project_id=project_id,
        title="Project Intake",
        content=content_str,
        created_by_id=project.created_by_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {"status": "ok", "document_id": str(doc.id)}


@router.get("/{project_id}/intake", response_model=ProjectIntakeRead)
def get_project_intake(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Fetch the latest "Project Intake" document for this project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = (
        db.query(ProjectDocument)
        .filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.title == "Project Intake",
        )
        .order_by(ProjectDocument.created_at.desc())
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Project intake not found")

    try:
        content_dict = json.loads(doc.content or "{}")
    except json.JSONDecodeError:
        content_dict = {}

    return ProjectIntakeRead(
        project_id=project_id,
        document_id=doc.id,
        title=doc.title,
        content=content_dict,
        created_at=doc.created_at,
    )


@router.patch("/{project_id}/intake", response_model=ProjectIntakeRead)
def patch_project_intake(
    project_id: UUID,
    payload: ProjectIntakePatch,
    db: Session = Depends(get_db),
):
    """
    Apply a partial JSON patch to the existing intake document.

    - Fetches latest "Project Intake" for project
    - Deep-merges `payload.patch` into existing JSON
    - Saves updated JSON back into the same document
    - Returns updated intake document
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = (
        db.query(ProjectDocument)
        .filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.title == "Project Intake",
        )
        .order_by(ProjectDocument.created_at.desc())
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Project intake not found")

    try:
        existing_content = json.loads(doc.content or "{}")
    except json.JSONDecodeError:
        existing_content = {}

    if not isinstance(existing_content, dict):
        existing_content = {}

    merged = _deep_merge(existing_content, payload.patch)

    doc.content = json.dumps(merged, indent=2)
    db.commit()
    db.refresh(doc)

    return ProjectIntakeRead(
        project_id=project_id,
        document_id=doc.id,
        title=doc.title,
        content=merged,
        created_at=doc.created_at,
    )
