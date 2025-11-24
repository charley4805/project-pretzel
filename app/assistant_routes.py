# app/assistant_routes.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas, deps

# THIS is what main.py imports: `router`
router = APIRouter(
    prefix="/projects",
    tags=["assistant"],
)


@router.post("/{project_id}/assistant/chat", response_model=schemas.ProjectAssistantResponse)
async def project_assistant_chat(
    project_id: UUID,
    payload: schemas.ProjectAssistantRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Project-aware AI assistant endpoint.

    - Ensures project exists
    - Ensures user is a member
    - Logs user message in `messages`
    - Generates assistant reply (placeholder for LangGraph)
    - Logs assistant message + AI run in `ai_run_logs`
    """

    # ----- Project + membership checks -----
    project = (
        db.query(models.Project)
        .filter(models.Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )

    # ----- Save user message -----
    user_msg = models.Message(
        project_id=project.id,
        sender_id=current_user.id,
        content=payload.message,
        message_type="user",
    )
    db.add(user_msg)
    db.flush()  # get generated ID without full commit

    # ----- Call AI (placeholder for LangGraph integration) -----
    role_name = membership.role.name if membership.role else "Collaborator"

    # TODO: plug in real LangGraph call here.
    ai_text = (
        f"[Pretzel Assistant for '{project.name}' as {role_name}] "
        f"You said: {payload.message}"
    )

    # ----- Save assistant message -----
    ai_msg = models.Message(
        project_id=project.id,
        sender_id=None,
        content=ai_text,
        message_type="assistant",
    )
    db.add(ai_msg)

    # ----- Log AI run -----
    run_log = models.AIRunLog(
        project_id=project.id,
        user_id=current_user.id,
        input_message=payload.message,
        output_message=ai_text,
        tools_used=None,
    )
    db.add(run_log)

    db.commit()
    db.refresh(user_msg)
    db.refresh(ai_msg)
    db.refresh(run_log)

    return schemas.ProjectAssistantResponse(
        reply=ai_text,
        project_id=str(project.id),
        user_message_id=str(user_msg.id),
        assistant_message_id=str(ai_msg.id),
        run_id=str(run_log.id),
    )
# app/assistant_routes.py (add below project_assistant_chat)

@router.get("/{project_id}/assistant/history", response_model=schemas.ProjectAssistantHistoryResponse)
async def get_project_assistant_history(
    project_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Return recent chat history (user + assistant messages) for this project.
    """

    # Ensure project exists
    project = (
        db.query(models.Project)
        .filter(models.Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Ensure user is a member
    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )

    # Fetch last N messages for this project
    q = (
        db.query(models.Message)
        .filter(
            models.Message.project_id == project_id,
            models.Message.message_type.in_(["user", "assistant"]),
        )
        .order_by(models.Message.created_at.asc())
        .limit(100)   # adjust if you want more/less history
    )

    rows = q.all()

    messages = [
        schemas.ProjectAssistantMessage(
            id=str(m.id),
            role="user" if m.message_type == "user" else "assistant",
            content=m.content,
            created_at=m.created_at,
        )
        for m in rows
    ]

    return schemas.ProjectAssistantHistoryResponse(messages=messages)
