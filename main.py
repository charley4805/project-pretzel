import secrets
from datetime import datetime, timezone
from uuid import UUID
from typing import List, Optional

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assistant_routes import router as assistant_router
from app.database import Base, engine
from app.deps import get_db
from app import models, schemas
from app.auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)

# 👉 Import your compiled LangGraph
from app.graph import app_graph  # rename to `from graph import app_graph` if you rename the file


app = FastAPI()

app.include_router(assistant_router)

# --- CORS so frontend can call FastAPI in dev ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dev-time: create tables
Base.metadata.create_all(bind=engine)


# ---------- CHAT REQUEST MODEL ----------

class ChatRequest(BaseModel):
    message: str
    history: List[str] = []
    projectId: Optional[str] = None


# ---------- AUTH HELPERS ----------

def get_current_user(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
) -> models.User:
    """
    Extracts the Bearer token from the Authorization header,
    decodes it, and returns the current User from the DB.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format.")

    token = parts[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    try:
        user_id = UUID(payload["sub"])
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token subject.")

    user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive.")

    return user


# ---------- BASIC ROUTES ----------

@app.get("/")
def root():
    return {"status": "FastAPI running"}


# ---------- ROLES & PERMISSIONS ENDPOINTS ----------

@app.get("/permissions", response_model=List[schemas.PermissionRead])
def list_permissions(db: Session = Depends(get_db)):
    perms = (
        db.query(models.Permission)
        .order_by(models.Permission.category, models.Permission.key)
        .all()
    )
    return perms


@app.get("/roles", response_model=List[schemas.RoleWithPermissionsRead])
def list_roles(db: Session = Depends(get_db)):
    roles = (
        db.query(models.Role)
        .order_by(models.Role.sort_order, models.Role.name)
        .all()
    )

    results: List[schemas.RoleWithPermissionsRead] = []

    for role in roles:
        perm_objs = [rp.permission for rp in role.permissions if rp.allowed]

        results.append(
            schemas.RoleWithPermissionsRead(
                id=role.id,
                key=role.key,
                name=role.name,
                description=role.description,
                sort_order=role.sort_order,
                permissions=[
                    schemas.PermissionRead.model_validate(p)
                    for p in perm_objs
                ],
            )
        )

    return results


# ---------- AUTH ROUTES (email or phone + password) ----------

@app.post("/auth/register", response_model=schemas.UserRead)
def register_user(payload: schemas.UserRegisterRequest, db: Session = Depends(get_db)):
    # Require at least email or phone
    if not payload.email and not payload.phone_number:
        raise HTTPException(status_code=400, detail="Email or phone_number is required.")

    # Check if user already exists by email or phone
    existing = None
    if payload.email:
        existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if not existing and payload.phone_number:
        existing = db.query(models.User).filter(models.User.phone_number == payload.phone_number).first()

    if existing:
        raise HTTPException(status_code=400, detail="User with that email/phone already exists.")

    user = models.User(
        email=payload.email,
        phone_number=payload.phone_number,
        full_name=payload.full_name,
        company_name=payload.company_name,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login_user(payload: schemas.UserLoginRequest, db: Session = Depends(get_db)):
    # Try identifier as email, then as phone
    user = (
        db.query(models.User)
        .filter(
            (models.User.email == payload.identifier)
            | (models.User.phone_number == payload.identifier)
        )
        .first()
    )

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive.")

    access_token = create_access_token(str(user.id))

    return schemas.TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=schemas.UserRead.model_validate(user),
    )


# ---------- CURRENT USER PROFILE ----------

@app.get("/users/me", response_model=schemas.UserRead)
def get_current_user_profile(
    current_user: models.User = Depends(get_current_user),
):
    return current_user


# ---------- PROJECT CREATION ----------

@app.post("/projects", response_model=schemas.ProjectWithRoleSummary)
def create_project(
    payload: schemas.ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create a new project and automatically assign the current user
    as the Project Manager (PROJECT_MANAGER role).
    """

    # Create the project
    project = models.Project(
        name=payload.name,
        description=payload.description,
        status="active",
        created_by_id=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(project)
    db.flush()  # get project.id

    # Find PROJECT_MANAGER role
    pm_role = db.query(models.Role).filter(models.Role.key == "PROJECT_MANAGER").first()
    if not pm_role:
        raise HTTPException(
            status_code=500,
            detail="PROJECT_MANAGER role not found. Did you run seed_roles?",
        )

    # Create membership for current user as PM
    membership = models.ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role_id=pm_role.id,
    )
    db.add(membership)
    db.commit()
    db.refresh(project)

    return schemas.ProjectWithRoleSummary(
        project_id=project.id,
        project_name=project.name,
        description=project.description,
        status=project.status,
        role_key=pm_role.key,
        role_name=pm_role.name,
    )


# ---------- "MY PROJECTS" DASHBOARD ----------

@app.get("/projects", response_model=List[schemas.ProjectWithRoleSummary])
def list_my_projects(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    memberships = (
        db.query(models.ProjectMember, models.Project, models.Role)
        .join(models.Project, models.ProjectMember.project_id == models.Project.id)
        .outerjoin(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(models.ProjectMember.user_id == current_user.id)
        .all()
    )

    results: List[schemas.ProjectWithRoleSummary] = []

    for pm, project, role in memberships:
        results.append(
            schemas.ProjectWithRoleSummary(
                project_id=project.id,
                project_name=project.name,
                description=project.description,
                status=project.status,
                role_key=role.key if role else None,
                role_name=role.name if role else None,
            )
        )

    return results


# ---------- SINGLE PROJECT (WITH MY ROLE) ----------

@app.get("/projects/{project_id}", response_model=schemas.ProjectWithRoleSummary)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    project = (
        db.query(models.Project)
        .filter(models.Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    membership_row = (
        db.query(models.ProjectMember, models.Role)
        .outerjoin(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )

    if not membership_row:
        raise HTTPException(status_code=403, detail="You are not a member of this project.")

    membership, role = membership_row

    return schemas.ProjectWithRoleSummary(
        project_id=project.id,
        project_name=project.name,
        description=project.description,
        status=project.status,
        role_key=role.key if role else None,
        role_name=role.name if role else None,
    )


# ---------- PROJECT MEMBERS LIST ----------

@app.get(
    "/projects/{project_id}/members",
    response_model=List[schemas.ProjectMemberDetail],
)
def list_project_members(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Ensure caller is at least a member of this project
    caller_membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )

    if not caller_membership:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this project.",
        )

    # Fetch members with user + role
    rows = (
        db.query(models.ProjectMember, models.User, models.Role)
        .join(models.User, models.ProjectMember.user_id == models.User.id)
        .outerjoin(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(models.ProjectMember.project_id == project_id)
        .all()
    )

    members: List[schemas.ProjectMemberDetail] = []

    for pm, user, role in rows:
        members.append(
            schemas.ProjectMemberDetail(
                user_id=user.id,
                full_name=user.full_name,
                email=user.email,
                phone_number=user.phone_number,
                role_key=role.key if role else None,
                role_name=role.name if role else None,
            )
        )

    return members


# ---------- INVITE CREATION (PM only) ----------

@app.post(
    "/projects/{project_id}/invites",
    response_model=schemas.InviteCreatedResponse,
)
def create_project_invite(
    project_id: UUID,
    payload: schemas.InviteCreateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    PM-only endpoint to create an invite for a project.
    Invitee can be specified by email or phone.
    Returns an invite token the frontend can wrap in
    a link (for email/SMS) or QR code.
    """

    # Require email or phone for the invitee
    if not payload.invitee_email and not payload.invitee_phone:
        raise HTTPException(status_code=400, detail="invitee_email or invitee_phone is required.")

    # Ensure project exists
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Check that inviter is PM on this project
    membership = (
        db.query(models.ProjectMember)
        .join(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )

    if not membership or not membership.role or membership.role.key != "PROJECT_MANAGER":
        raise HTTPException(
            status_code=403,
            detail="Only the Project Manager can send invites for this project.",
        )

    # Generate a unique token for the invite
    token = secrets.token_urlsafe(32)

    invite = models.ProjectInvite(
        project_id=project.id,
        inviter_id=current_user.id,
        invitee_email=payload.invitee_email,
        invitee_phone=payload.invitee_phone,
        token=token,
        status="pending",
    )

    db.add(invite)
    db.commit()
    db.refresh(invite)

    return schemas.InviteCreatedResponse(
        token=invite.token,
        project_id=project.id,
        project_name=project.name,
        invitee_email=invite.invitee_email,
        invitee_phone=invite.invitee_phone,
        status=invite.status,
    )


# ---------- INVITE INFO + ACCEPT (invitee side) ----------

@app.get("/invites/{token}", response_model=schemas.InviteInfo)
def get_invite(token: str, db: Session = Depends(get_db)):
    invite = (
        db.query(models.ProjectInvite)
        .filter(models.ProjectInvite.token == token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")

    project = invite.project
    has_account = invite.invitee_user_id is not None

    return schemas.InviteInfo(
        project_name=project.name,
        project_id=project.id,
        status=invite.status,
        invitee_email=invite.invitee_email,
        invitee_phone=invite.invitee_phone,
        has_account=has_account,
    )


@app.post("/invites/{token}/accept", response_model=schemas.InviteAcceptResponse)
def accept_invite(
    token: str,
    payload: schemas.InviteAcceptRequest,
    db: Session = Depends(get_db),
):
    invite = (
        db.query(models.ProjectInvite)
        .filter(models.ProjectInvite.token == token)
        .first()
    )
    if not invite or invite.status != "pending":
        raise HTTPException(status_code=400, detail="Invite is invalid or not pending.")

    # If invite already linked to a user, just mark accepted
    user = invite.invitee_user

    # If user doesn't exist yet, create from this payload
    if not user:
        if not (payload.email or payload.phone_number):
            raise HTTPException(status_code=400, detail="Email or phone_number required to create account.")

        # Check if someone already exists with this email/phone
        existing = None
        if payload.email:
            existing = db.query(models.User).filter(models.User.email == payload.email).first()
        if not existing and payload.phone_number:
            existing = db.query(models.User).filter(models.User.phone_number == payload.phone_number).first()

        if existing:
            user = existing
        else:
            if not payload.password:
                raise HTTPException(status_code=400, detail="Password is required for new account.")
            user = models.User(
                email=payload.email or invite.invitee_email,
                phone_number=payload.phone_number or invite.invitee_phone,
                full_name=payload.full_name,
                company_name=payload.company_name,
                password_hash=hash_password(payload.password),
                is_active=True,
            )
            db.add(user)
            db.flush()  # get user.id

        invite.invitee_user_id = user.id

    # Mark invite accepted; PM will later approve & assign role
    invite.status = "accepted"
    invite.accepted_at = datetime.now(timezone.utc)

    db.add(invite)
    db.commit()
    db.refresh(invite)

    project = invite.project

    return schemas.InviteAcceptResponse(
        message=f'You have accepted to join project "{project.name}". The PM has been notified and will assign your role.',
        project_id=project.id,
        project_name=project.name,
    )


# ---------- PM VIEW: Invites awaiting approval ----------

@app.get(
    "/projects/{project_id}/invites/awaiting-approval",
    response_model=List[schemas.InvitePendingForPM],
)
def list_invites_awaiting_approval(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Ensure caller is PM on this project
    membership = (
        db.query(models.ProjectMember)
        .join(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership or not membership.role or membership.role.key != "PROJECT_MANAGER":
        raise HTTPException(
            status_code=403,
            detail="Only the Project Manager can view invites for this project.",
        )

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    invites = (
        db.query(models.ProjectInvite)
        .filter(
            models.ProjectInvite.project_id == project_id,
            models.ProjectInvite.status == "accepted",
        )
        .all()
    )

    results: List[schemas.InvitePendingForPM] = []

    for inv in invites:
        # Only include if there's no ProjectMember yet
        if inv.invitee_user_id:
            existing_member = (
                db.query(models.ProjectMember)
                .filter(
                    models.ProjectMember.project_id == project_id,
                    models.ProjectMember.user_id == inv.invitee_user_id,
                )
                .first()
            )
            if existing_member:
                continue

        invitee = inv.invitee_user

        results.append(
            schemas.InvitePendingForPM(
                id=inv.id,
                project_id=project.id,
                project_name=project.name,
                invitee_user_id=inv.invitee_user_id,
                invitee_name=invitee.full_name if invitee else None,
                invitee_email=inv.invitee_email,
                invitee_phone=inv.invitee_phone,
                status=inv.status,
                accepted_at=inv.accepted_at,
            )
        )

    return results


# ---------- PM ACTION: Approve invite + assign role ----------

@app.post(
    "/projects/{project_id}/invites/{invite_id}/approve",
    response_model=schemas.InviteApproveResponse,
)
def approve_invite_and_assign_role(
    project_id: UUID,
    invite_id: UUID,
    payload: schemas.InviteApproveRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Ensure caller is PM on this project
    membership = (
        db.query(models.ProjectMember)
        .join(models.Role, models.ProjectMember.role_id == models.Role.id)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership or not membership.role or membership.role.key != "PROJECT_MANAGER":
        raise HTTPException(
            status_code=403,
            detail="Only the Project Manager can approve invites for this project.",
        )

    invite = (
        db.query(models.ProjectInvite)
        .filter(
            models.ProjectInvite.id == invite_id,
            models.ProjectInvite.project_id == project_id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.status != "accepted":
        raise HTTPException(status_code=400, detail="Invite is not in accepted state.")

    if not invite.invitee_user_id:
        raise HTTPException(status_code=400, detail="Invitee has not created an account yet.")

    user = invite.invitee_user

    # Find the role by key
    role = db.query(models.Role).filter(models.Role.key == payload.role_key).first()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role_key.")

    # Check if membership exists; if so update; otherwise create
    existing_member = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == user.id,
        )
        .first()
    )

    if existing_member:
        existing_member.role_id = role.id
        db.add(existing_member)
    else:
        new_member = models.ProjectMember(
            project_id=project_id,
            user_id=user.id,
            role_id=role.id,
        )
        db.add(new_member)

    db.commit()

    project = invite.project

    return schemas.InviteApproveResponse(
        project_id=project.id,
        project_name=project.name,
        user_id=user.id,
        role_key=role.key,
        message=f'User "{user.full_name or user.email or user.phone_number}" has been added to project "{project.name}" as {role.name}.',
    )


# ---------- CHAT HELPERS (LangGraph glue) ----------

def append_user_turn(history: List[str], user_message: str) -> List[str]:
    """
    Take the existing history from the frontend and append
    the new 'USER: ...' turn in the format your graph expects.
    """
    new_history = list(history)
    new_history.append(f"USER: {user_message}")
    return new_history


def extract_latest_assistant_reply(messages: List[str]) -> str:
    """
    Find the latest 'ASSISTANT: ...' message in the graph output
    and return just the text.
    """
    for entry in reversed(messages):
        if entry.lower().startswith("assistant:"):
            return entry.split(":", 1)[1].strip()

    # Fallback if something unexpected happens
    return "Sorry, I couldn't generate a response."


# ---------- CHAT ROUTE (now powered by LangGraph) ----------

@app.post("/chat")
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user),
):
    """
    Chat endpoint used by the frontend AI Assistant.

    Request:
      {
        "message": "string",
        "history": ["USER: ...", "ASSISTANT: ..."],
        "projectId": "uuid-string | null"
      }

    Response:
      {
        "reply": "assistant message text",
        "messages": ["USER: ...", "ASSISTANT: ...", ...],
        "projectId": "...",
        "userId": "..."
      }
    """
    try:
        # 1) Append the current user message in the same string format your graph expects
        messages_for_graph = append_user_turn(req.history, req.message)

        # 2) Invoke the compiled LangGraph agent (router + tools + assistant)
        result_state = app_graph.invoke({"messages": messages_for_graph,"projectId": req.projectId,})

        # 3) Get back the full conversation list (your nodes already append ASSISTANT messages)
        updated_history: List[str] = result_state.get("messages", messages_for_graph)

        # 4) Extract the latest assistant reply for convenience in the frontend
        reply_text = extract_latest_assistant_reply(updated_history)

        return {
            "reply": reply_text,
            "messages": updated_history,
            "projectId": req.projectId,
            "userId": str(current_user.id) if current_user else None,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
