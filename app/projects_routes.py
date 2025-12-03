# app/project_routes.py
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
from app import models, schemas

router = APIRouter()


# ---------- Helpers ----------


def log_action(
    db: Session,
    user_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID | str,
    project_id: UUID | None = None,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """
    Write a generic audit log entry.
    Commit is handled by the caller.
    """
    log = models.AuditLog(
        user_id=user_id,
        project_id=project_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata_json=metadata or {},
    )
    db.add(log)


def _to_date(value: Any) -> date:
    """
    Coerce a variety of incoming types into a date object.
    Accepts date, datetime, or ISO date string.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Cannot interpret value as date: {value!r}")


def build_project_summary(
    db: Session,
    project: models.Project,
    role_key: str | None,
    role_name: str | None,
    current_user: models.User,
) -> schemas.ProjectWithRoleSummary:
    """
    Compute the ProjectWithRoleSummary DTO for a single project,
    including completion %, today's activities, and unread messages.
    """
    today = date.today()

    # ---- Completion percentage based on ActivitySchedule rows ----
    total_schedules = (
        db.query(models.ActivitySchedule)
        .filter(models.ActivitySchedule.project_id == project.id)
        .count()
    )

    completed_schedules = (
        db.query(models.ActivitySchedule)
        .filter(
            models.ActivitySchedule.project_id == project.id,
            models.ActivitySchedule.status == models.ActivityStatus.COMPLETED,
        )
        .count()
    )

    completion_percentage = (
        float(completed_schedules) / float(total_schedules) * 100.0
        if total_schedules > 0
        else 0.0
    )

    # ---- Today's activities (schedules whose scheduled_start_date == today) ----
    todays_rows = (
        db.query(
            models.ActivitySchedule,
            models.Activity,
            models.ProjectMember,
            models.User,
        )
        .join(models.Activity, models.ActivitySchedule.activity_id == models.Activity.id)
        .outerjoin(
            models.ProjectMember,
            models.ActivitySchedule.project_member_id == models.ProjectMember.id,
        )
        .outerjoin(
            models.User,
            models.ProjectMember.user_id == models.User.id,
        )
        .filter(
            models.ActivitySchedule.project_id == project.id,
            models.ActivitySchedule.scheduled_start_date == today,
        )
        .order_by(models.ActivitySchedule.scheduled_start_date)
        .all()
    )

    todays_summaries: list[schemas.ProjectActivityTodaySummary] = []

    for sched, activity, pm, user in todays_rows:
        member_name: str | None = None
        member_on_site = False

        if pm is not None and user is not None:
            member_name = user.full_name or user.email or None

            # "On site" = open check-in for this member today
            open_checkin_exists = (
                db.query(models.MemberCheckIn)
                .filter(
                    models.MemberCheckIn.project_id == project.id,
                    models.MemberCheckIn.project_member_id == pm.id,
                    models.MemberCheckIn.check_out_time.is_(None),
                    sa_func.date(models.MemberCheckIn.check_in_time) == today,
                )
                .count()
                > 0
            )
            member_on_site = open_checkin_exists

        todays_summaries.append(
            schemas.ProjectActivityTodaySummary(
                id=sched.id,
                title=activity.name,
                member_name=member_name,
                member_on_site=member_on_site,
            )
        )

    # ---- Unread messages flag ----
    sub_read = (
        db.query(models.MessageRead.message_id)
        .filter(models.MessageRead.user_id == current_user.id)
        .subquery()
    )

    unread_exists = (
        db.query(models.Message)
        .filter(
            models.Message.project_id == project.id,
            models.Message.sender_id != current_user.id,
            ~models.Message.id.in_(sub_read),
        )
        .count()
        > 0
    )

    # ---- Status key ----
    status_key: str | None = None
    # If you added ProjectStatus, prefer its key; otherwise fall back to string status.
    if getattr(project, "status_ref", None) is not None and getattr(
        project.status_ref, "key", None
    ):
        status_key = project.status_ref.key
    elif project.status:
        status_key = project.status

    # 🔹 NEW: project_type, end_date, is_owner
    return schemas.ProjectWithRoleSummary(
        project_id=project.id,
        project_name=project.name,
        description=project.description,
        status=status_key,
        role_key=role_key,
        role_name=role_name,
        address_line1=getattr(project, "address_line1", None),
        address_line2=getattr(project, "address_line2", None),
        city=project.city,
        state=project.state,
        postal_code=project.postal_code,
        latitude=project.latitude,
        longitude=project.longitude,
        completion_percentage=completion_percentage,
        has_unread_messages=unread_exists,
        todays_activities=todays_summaries,
        project_type=getattr(project, "project_type", None),
        end_date=getattr(project, "end_date", None),
        is_owner=(project.created_by_id == current_user.id),
    )


# ---------- ROUTES: PROJECTS ----------


@router.post("/projects")
def create_project(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a Project from the new-project intake JSON.
    """

    # --- Infer name & description ----------------------------
    address = payload.get("address") or {}

    address_line1 = (
        address.get("line1")
        or address.get("address1")
        or payload.get("address_line1")
    )
    address_line2 = (
        address.get("line2")
        or address.get("address2")
        or payload.get("address_line2")
    )

    city = address.get("city") or payload.get("city")
    state = address.get("state") or payload.get("state")
    postal_code = (
        address.get("postal_code")
        or address.get("zip")
        or address.get("zip_code")
        or payload.get("postal_code")
    )

    project_type = payload.get("project_type")

    raw_end_date = payload.get("end_date")
    end_date: Optional[date] = None
    if raw_end_date:
        try:
            end_date = _to_date(raw_end_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Name / description
    name = (
        payload.get("project_name_final")
        or payload.get("project_name")
        or payload.get("name")
        or address_line1
        or "Untitled project"
    )
    description = (
        payload.get("description")
        or payload.get("summary")
        or payload.get("project_summary")
        or ""
    )

    # Default status
    default_status_key = "ON_TRACK"
    status_row = None
    if hasattr(models, "ProjectStatus"):
        status_row = (
            db.query(models.ProjectStatus)
            .filter(models.ProjectStatus.key == default_status_key)
            .first()
        )

    project = models.Project(
        name=name,
        description=description,
        address_line1=address_line1,
        address_line2=address_line2,
        city=city,
        state=state,
        postal_code=postal_code,
        project_type=project_type,
        end_date=end_date,
        created_by_id=current_user.id,
        status=default_status_key,
        status_id=status_row.id if status_row else None,
    )
    db.add(project)
    db.flush()  # get project.id before membership

    # --- Make current user a member (as PM if we can) --------
    pm_role = (
        db.query(models.Role)
        .filter(
            models.Role.key.in_(
                ["ProjectManager", "project_manager", "pm", "PROJECT_MANAGER"]
            )
        )
        .first()
    )

    member = models.ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role_id=pm_role.id if pm_role else None,
    )
    db.add(member)

    # --- Audit log -------------------------------------------
    log_action(
        db=db,
        user_id=current_user.id,
        action="PROJECT_CREATED",
        entity_type="Project",
        entity_id=project.id,
        project_id=project.id,
        metadata={
            "name": project.name,
            "city": project.city,
            "state": project.state,
            "postal_code": project.postal_code,
            "project_type": project.project_type,
            "end_date": project.end_date.isoformat() if project.end_date else None,
        },
    )

    db.commit()
    db.refresh(project)

    return {
        "id": str(project.id),
        "project_id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "address_line1": project.address_line1,
        "address_line2": project.address_line2,
        "city": project.city,
        "state": project.state,
        "postal_code": project.postal_code,
        "project_type": project.project_type,
        "end_date": project.end_date.isoformat() if project.end_date else None,
    }


@router.get(
    "/projects/my",
    response_model=List[schemas.ProjectWithRoleSummary],
)
def list_my_projects(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return all projects where the current user is a member,
    plus their role, completion %, today's activities, and unread flag.
    """

    rows = (
        db.query(
            models.Project,
            models.Role.key.label("role_key"),
            models.Role.name.label("role_name"),
        )
        .join(
            models.ProjectMember,
            models.ProjectMember.project_id == models.Project.id,
        )
        .outerjoin(
            models.Role,
            models.Role.id == models.ProjectMember.role_id,
        )
        .filter(models.ProjectMember.user_id == current_user.id)
        .order_by(models.Project.created_at.desc())
        .all()
    )

    summaries: list[schemas.ProjectWithRoleSummary] = []

    for project, role_key, role_name in rows:
        summaries.append(
            build_project_summary(
                db=db,
                project=project,
                role_key=role_key,
                role_name=role_name,
                current_user=current_user,
            )
        )

    return summaries


@router.get(
    "/projects/{project_id}",
    response_model=schemas.ProjectWithRoleSummary,
)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return a single project summary for the current user.
    """

    row = (
        db.query(
            models.Project,
            models.Role.key.label("role_key"),
            models.Role.name.label("role_name"),
        )
        .join(
            models.ProjectMember,
            models.ProjectMember.project_id == models.Project.id,
        )
        .outerjoin(
            models.Role,
            models.Role.id == models.ProjectMember.role_id,
        )
        .filter(
            models.Project.id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    project, role_key, role_name = row

    return build_project_summary(
        db=db,
        project=project,
        role_key=role_key,
        role_name=role_name,
        current_user=current_user,
    )


@router.patch(
    "/projects/{project_id}",
    response_model=schemas.ProjectWithRoleSummary,
)
def update_project(
    project_id: UUID,
    payload: schemas.ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update a project (name, description, status, address, type, end date).
    Logs changes in AuditLog.

    🔹 Only the project creator is allowed to update.
    """

    row = (
        db.query(
            models.Project,
            models.Role.key.label("role_key"),
            models.Role.name.label("role_name"),
        )
        .join(
            models.ProjectMember,
            models.ProjectMember.project_id == models.Project.id,
        )
        .outerjoin(
            models.Role,
            models.Role.id == models.ProjectMember.role_id,
        )
        .filter(
            models.Project.id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    project, role_key, role_name = row

    # 🔹 Enforce creator-only updates
    if project.created_by_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the project creator can update this project.",
        )

    changes: Dict[str, Dict[str, Any]] = {}

    def apply(field: str, new_value: Any):
        old_value = getattr(project, field)
        if new_value is not None and new_value != old_value:
            setattr(project, field, new_value)
            changes[field] = {"old": old_value, "new": new_value}

    apply("name", payload.name)
    apply("description", payload.description)
    apply("city", payload.city)
    apply("state", payload.state)
    apply("postal_code", payload.postal_code)

    # 🔹 NEW: project_type
    if hasattr(payload, "project_type"):
        apply("project_type", payload.project_type)

    # 🔹 NEW: end_date (normalized)
    if getattr(payload, "end_date", None) is not None:
        try:
            new_end_date = _to_date(payload.end_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        old_end_date = getattr(project, "end_date", None)
        if new_end_date != old_end_date:
            project.end_date = new_end_date
            changes["end_date"] = {"old": old_end_date, "new": new_end_date}

    # Status handling (normalized + string)
    if payload.status is not None:
        status_key = payload.status.upper()
        old_status = project.status
        project.status = status_key

        old_status_id = getattr(project, "status_id", None)
        new_status_id = old_status_id
        if hasattr(models, "ProjectStatus"):
            status_row = (
                db.query(models.ProjectStatus)
                .filter(models.ProjectStatus.key == status_key)
                .first()
            )
            new_status_id = status_row.id if status_row else None
            if hasattr(project, "status_id"):
                project.status_id = new_status_id
        else:
            status_row = None  # noqa

        if status_key != old_status:
            changes["status"] = {"old": old_status, "new": status_key}
        if old_status_id != new_status_id:
            changes["status_id"] = {"old": old_status_id, "new": new_status_id}

    if changes:
        log_action(
            db=db,
            user_id=current_user.id,
            action="PROJECT_UPDATED",
            entity_type="Project",
            entity_id=project.id,
            project_id=project.id,
            metadata={"changes": changes},
        )

    db.commit()
    db.refresh(project)

    return build_project_summary(
        db=db,
        project=project,
        role_key=role_key,
        role_name=role_name,
        current_user=current_user,
    )


@router.get(
    "/projects/{project_id}/members",
    response_model=List[schemas.ProjectMemberDetail],
)
def get_project_members(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return all members for a given project.
    """

    project_exists = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not project_exists:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    rows = (
        db.query(
            models.User.id.label("user_id"),
            models.User.full_name,
            models.User.email,
            models.User.phone_number,
            models.Role.key.label("role_key"),
            models.Role.name.label("role_name"),
        )
        .join(
            models.ProjectMember,
            models.ProjectMember.user_id == models.User.id,
        )
        .outerjoin(
            models.Role,
            models.Role.id == models.ProjectMember.role_id,
        )
        .filter(models.ProjectMember.project_id == project_id)
        .all()
    )

    return [
        schemas.ProjectMemberDetail(
            user_id=row.user_id,
            full_name=row.full_name,
            email=row.email,
            phone_number=row.phone_number,
            role_key=row.role_key,
            role_name=row.role_name,
        )
        for row in rows
    ]


# ---------- ACTIVITY CATALOG + SCHEDULING ----------


@router.get(
    "/activities",
    response_model=List[schemas.ActivityDefinitionRead],
)
def list_activities(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List all activity definitions (global catalog + custom).
    """
    rows = (
        db.query(models.Activity)
        .order_by(models.Activity.name.asc())
        .all()
    )
    return rows


@router.post(
    "/activities",
    response_model=schemas.ActivityDefinitionRead,
)
def create_activity_definition(
    payload: schemas.ActivityDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a new activity definition in the catalog (custom activity).
    """
    activity = models.Activity(
        name=payload.name,
        description=payload.description,
        is_custom=True,
        created_by_id=current_user.id,
    )
    db.add(activity)

    log_action(
        db=db,
        user_id=current_user.id,
        action="ACTIVITY_DEFINITION_CREATED",
        entity_type="Activity",
        entity_id=activity.id,
        project_id=None,
        metadata={"name": activity.name},
    )

    db.commit()
    db.refresh(activity)
    return activity


@router.get(
    "/projects/{project_id}/activity-schedules",
    response_model=List[schemas.ActivityScheduleRead],
)
def list_activity_schedules_for_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    List all scheduled activities for a project, ordered by scheduled_start_date.
    """
    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    rows = (
        db.query(
            models.ActivitySchedule,
            models.Activity,
        )
        .join(models.Activity, models.ActivitySchedule.activity_id == models.Activity.id)
        .filter(models.ActivitySchedule.project_id == project_id)
        .order_by(
            models.ActivitySchedule.scheduled_start_date.asc(),
            models.Activity.name.asc(),
        )
        .all()
    )

    result: List[schemas.ActivityScheduleRead] = []
    for sched, activity in rows:
        result.append(
            schemas.ActivityScheduleRead(
                id=sched.id,
                project_id=sched.project_id,
                activity_id=sched.activity_id,
                activity_name=activity.name,
                description=activity.description,
                project_member_id=sched.project_member_id,
                scheduled_start_date=sched.scheduled_start_date,
                scheduled_end_date=sched.scheduled_end_date,
                actual_start_date=sched.actual_start_date,
                actual_end_date=sched.actual_end_date,
                status=sched.status.value if sched.status else None,
            )
        )

    return result


@router.post(
    "/projects/{project_id}/activity-schedules",
    response_model=schemas.ActivityScheduleRead,
)
def create_activity_schedule(
    project_id: UUID,
    payload: schemas.ActivityScheduleItemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Schedule a catalog activity onto a project.
    """

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    activity = (
        db.query(models.Activity)
        .filter(models.Activity.id == payload.activity_id)
        .first()
    )
    if not activity:
        raise HTTPException(status_code=400, detail="Invalid activity_id")

    assigned_pm = None
    if payload.project_member_id is not None:
        assigned_pm = (
            db.query(models.ProjectMember)
            .filter(
                models.ProjectMember.id == payload.project_member_id,
                models.ProjectMember.project_id == project_id,
            )
            .first()
        )
        if not assigned_pm:
            raise HTTPException(
                status_code=400,
                detail="Invalid project_member_id for this project",
            )

    sched = models.ActivitySchedule(
        project_id=project_id,
        activity_id=activity.id,
        project_member_id=assigned_pm.id if assigned_pm else None,
        scheduled_start_date=payload.scheduled_start_date,
        scheduled_end_date=payload.scheduled_end_date,
        status=models.ActivityStatus.SCHEDULED,
    )
    db.add(sched)
    db.flush()

    log_action(
        db=db,
        user_id=current_user.id,
        action="ACTIVITY_SCHEDULE_CREATED",
        entity_type="ActivitySchedule",
        entity_id=sched.id,
        project_id=project_id,
        metadata={
            "activity_name": activity.name,
            "scheduled_start_date": str(sched.scheduled_start_date),
            "scheduled_end_date": str(sched.scheduled_end_date)
            if sched.scheduled_end_date
            else None,
        },
    )

    db.commit()
    db.refresh(sched)

    return schemas.ActivityScheduleRead(
        id=sched.id,
        project_id=sched.project_id,
        activity_id=sched.activity_id,
        activity_name=activity.name,
        description=activity.description,
        project_member_id=sched.project_member_id,
        scheduled_start_date=sched.scheduled_start_date,
        scheduled_end_date=sched.scheduled_end_date,
        actual_start_date=sched.actual_start_date,
        actual_end_date=sched.actual_end_date,
        status=sched.status.value if sched.status else None,
    )


# GET catalog of activities (DB stored)
@router.get("/projects/{project_id}/activities/catalog")
def get_activity_catalog(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # user must be a member of the project
    exists = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not exists:
        raise HTTPException(status_code=403, detail="Not a project member.")

    items = (
        db.query(models.Activity)
        .order_by(models.Activity.name.asc())
        .all()
    )

    return [
        {
            "id": str(a.id),
            "name": a.name,
            "description": a.description,
            "is_custom": a.is_custom,
        }
        for a in items
    ]


@router.get("/projects/{project_id}/activities")
def list_project_activities(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Return all scheduled activities for this project, in the shape
    expected by the frontend `Activity` interface:
      {
        id: string,
        project_id: string,
        project_member_id?: number,
        title: string,
        description?: string,
        scheduled_date?: string (ISO),
        status?: string,
        completed_at?: string (ISO)
      }
    """

    # Ensure the current user is a member of the project
    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    # Join ActivitySchedule with Activity to pull the catalog info
    rows = (
        db.query(
            models.ActivitySchedule,
            models.Activity.name.label("activity_name"),
            models.Activity.description.label("activity_description"),
        )
        .join(
            models.Activity,
            models.Activity.id == models.ActivitySchedule.activity_id,
        )
        .filter(models.ActivitySchedule.project_id == project_id)
        .order_by(models.ActivitySchedule.scheduled_start_date.asc())
        .all()
    )

    activities: list[dict] = []
    for sched, activity_name, activity_description in rows:
        activities.append(
            {
                "id": str(sched.id),
                "project_id": str(sched.project_id),
                "project_member_id": sched.project_member_id,
                "title": activity_name,
                "description": activity_description,
                "scheduled_date": (
                    sched.scheduled_start_date.isoformat()
                    if sched.scheduled_start_date
                    else None
                ),
                "status": (
                    sched.status.value if hasattr(sched.status, "value") else sched.status
                ),
                "completed_at": (
                    sched.actual_end_date.isoformat()
                    if sched.actual_end_date
                    else None
                ),
            }
        )

    return activities


# 🔹 POST create scheduled activity (with optional new custom Activity)
@router.post("/projects/{project_id}/activities")
def create_scheduled_activity(
    project_id: UUID,
    payload: schemas.ActivityCreatePayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 0. Confirm membership
    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a project member.")

    # 1. Resolve or create the Activity
    activity_id: UUID | None = None

    # Case A: create a new custom activity
    create_custom = (
        payload.title.startswith("custom_") or payload.activity_id is None
    )

    if create_custom:
        new_activity = models.Activity(
            name=payload.title,
            description=payload.description,
            is_custom=True,
            created_by_id=current_user.id,
        )
        db.add(new_activity)
        db.flush()  # 🔑 get new_activity.id without committing yet
        activity_id = new_activity.id
    else:
        # Case B: use existing activity_id from payload
        activity = (
            db.query(models.Activity)
            .filter(models.Activity.id == payload.activity_id)
            .first()
        )
        if not activity:
            raise HTTPException(
                status_code=400,
                detail=f"Activity {payload.activity_id} not found",
            )
        activity_id = activity.id

    # 2. Who is this scheduled for?
    # If no project_member_id provided, default to the current membership.id
    assignee_member_id = payload.project_member_id or membership.id

    # 3. Create the scheduled row (now with a real activity_id)
    schedule = models.ActivitySchedule(
        project_id=project_id,
        activity_id=activity_id,  # ✅ no longer None
        project_member_id=assignee_member_id,  # assigned to someone on the project
        scheduled_start_date=payload.scheduled_date,
        scheduled_end_date=None,
        status=models.ActivityStatus.SCHEDULED,
    )

    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    return {
        "id": str(schedule.id),
        "title": payload.title,
        "scheduled_date": str(schedule.scheduled_start_date),
        "status": schedule.status.value,
    }


# ---------- CHECK-INS ----------


@router.post(
    "/projects/{project_id}/activities/{activity_id}/checkin",
)
def check_in_to_activity(
    project_id: UUID,
    activity_id: UUID,
    payload: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Check in the current user to a scheduled activity.

    NOTE: activity_id here refers to ActivitySchedule.id (scheduled row).
    """

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    sched = (
        db.query(models.ActivitySchedule)
        .filter(
            models.ActivitySchedule.id == activity_id,
            models.ActivitySchedule.project_id == project_id,
        )
        .first()
    )
    if not sched:
        raise HTTPException(status_code=404, detail="Activity schedule not found")

    # Close any open check-ins for this member on this project
    now = datetime.utcnow()
    open_checkins = (
        db.query(models.MemberCheckIn)
        .filter(
            models.MemberCheckIn.project_id == project_id,
            models.MemberCheckIn.project_member_id == membership.id,
            models.MemberCheckIn.check_out_time.is_(None),
        )
        .all()
    )
    for oc in open_checkins:
        oc.check_out_time = now

    notes = payload.get("notes")

    checkin = models.MemberCheckIn(
        project_id=project_id,
        project_member_id=membership.id,
        activity_schedule_id=sched.id,
        check_in_time=now,
        notes=notes,
    )
    db.add(checkin)

    log_action(
        db=db,
        user_id=current_user.id,
        action="CHECK_IN",
        entity_type="MemberCheckIn",
        entity_id=checkin.id,
        project_id=project_id,
        metadata={
            "activity_schedule_id": str(sched.id),
            "notes": notes,
        },
    )

    db.commit()
    db.refresh(checkin)

    return {
        "id": str(checkin.id),
        "project_id": str(checkin.project_id),
        "project_member_id": checkin.project_member_id,
        "activity_schedule_id": str(checkin.activity_schedule_id)
        if checkin.activity_schedule_id
        else None,
        "check_in_time": checkin.check_in_time.isoformat(),
        "check_out_time": checkin.check_out_time.isoformat()
        if checkin.check_out_time
        else None,
        "notes": checkin.notes,
    }


@router.post(
    "/checkins/{checkin_id}/checkout",
)
def check_out(
    checkin_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Check out of a previously opened check-in.
    """

    checkin = (
        db.query(models.MemberCheckIn)
        .filter(models.MemberCheckIn.id == checkin_id)
        .first()
    )
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.id == checkin.project_member_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized to check out this entry")

    if checkin.check_out_time is not None:
        return {
            "id": str(checkin.id),
            "project_id": str(checkin.project_id),
            "project_member_id": checkin.project_member_id,
            "activity_schedule_id": str(checkin.activity_schedule_id)
            if checkin.activity_schedule_id
            else None,
            "check_in_time": checkin.check_in_time.isoformat(),
            "check_out_time": checkin.check_out_time.isoformat(),
            "notes": checkin.notes,
        }

    now = datetime.utcnow()
    checkin.check_out_time = now

    log_action(
        db=db,
        user_id=current_user.id,
        action="CHECK_OUT",
        entity_type="MemberCheckIn",
        entity_id=checkin.id,
        project_id=checkin.project_id,
        metadata={
            "activity_schedule_id": str(checkin.activity_schedule_id)
            if checkin.activity_schedule_id
            else None
        },
    )

    db.commit()
    db.refresh(checkin)

    return {
        "id": str(checkin.id),
        "project_id": str(checkin.project_id),
        "project_member_id": checkin.project_member_id,
        "activity_schedule_id": str(checkin.activity_schedule_id)
        if checkin.activity_schedule_id
        else None,
        "check_in_time": checkin.check_in_time.isoformat(),
        "check_out_time": checkin.check_out_time.isoformat()
        if checkin.check_out_time
        else None,
        "notes": checkin.notes,
    }


# ---------- MESSAGES: list, create, mark read ----------


@router.get(
    "/projects/{project_id}/messages",
    response_model=List[schemas.ProjectMessageRead],
)
def get_project_messages(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    before: Optional[datetime] = Query(None),
):
    """
    Paginated list of messages for a project.
    - Returns latest messages first by default.
    """

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    q = (
        db.query(models.Message, models.User)
        .outerjoin(models.User, models.Message.sender_id == models.User.id)
        .filter(models.Message.project_id == project_id)
        .order_by(models.Message.created_at.desc())
    )

    if before is not None:
        q = q.filter(models.Message.created_at < before)

    rows = q.limit(limit).all()

    results: List[schemas.ProjectMessageRead] = []
    for message, user in rows:
        sender_name = None
        if user:
            sender_name = user.full_name or user.email

        attachments = [
            schemas.MessageAttachmentRead.from_orm(att)
            for att in message.attachments
        ]

        results.append(
            schemas.ProjectMessageRead(
                id=message.id,
                project_id=message.project_id,
                sender_id=message.sender_id,
                sender_name=sender_name,
                content=message.content,
                message_type=message.message_type,
                created_at=message.created_at,
                attachments=attachments,
            )
        )

    return results


@router.post(
    "/projects/{project_id}/messages",
    response_model=schemas.ProjectMessageRead,
)
def create_project_message(
    project_id: UUID,
    payload: schemas.ProjectMessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a new user message in a project.
    (Attachments will come from a separate upload flow later.)
    """

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    message = models.Message(
        project_id=project_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type="user",
    )
    db.add(message)
    db.flush()

    log_action(
        db=db,
        user_id=current_user.id,
        action="MESSAGE_SENT",
        entity_type="Message",
        entity_id=message.id,
        project_id=project_id,
        metadata={"content_preview": message.content[:120]},
    )

    db.commit()
    db.refresh(message)

    sender_name = current_user.full_name or current_user.email
    return schemas.ProjectMessageRead(
        id=message.id,
        project_id=message.project_id,
        sender_id=message.sender_id,
        sender_name=sender_name,
        content=message.content,
        message_type=message.message_type,
        created_at=message.created_at,
        attachments=[],
    )


@router.post(
    "/projects/{project_id}/messages/read",
)
def mark_project_messages_read(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Mark all messages in a project as read for the current user.
    """

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found or not accessible")

    existing_reads_subq = (
        db.query(models.MessageRead.message_id)
        .filter(models.MessageRead.user_id == current_user.id)
        .subquery()
    )

    unread_messages = (
        db.query(models.Message.id)
        .filter(
            models.Message.project_id == project_id,
            models.Message.sender_id != current_user.id,
            ~models.Message.id.in_(existing_reads_subq),
        )
        .all()
    )

    now = datetime.utcnow()
    created_count = 0

    for (message_id,) in unread_messages:
        read = models.MessageRead(
            message_id=message_id,
            user_id=current_user.id,
            read_at=now,
        )
        db.add(read)
        created_count += 1

    if created_count > 0:
        log_action(
            db=db,
            user_id=current_user.id,
            action="MESSAGES_MARKED_READ",
            entity_type="Message",
            entity_id=str(project_id),
            project_id=project_id,
            metadata={"messages_marked": created_count},
        )

    db.commit()

    return {
        "project_id": str(project_id),
        "messages_marked": created_count,
    }
