from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------
# USER MODELS
# ---------------------------------------------------------

class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None


class UserRead(UserBase):
    id: UUID
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserRegisterRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    password: str
    full_name: Optional[str] = None
    company_name: Optional[str] = None


class UserLoginRequest(BaseModel):
    # email OR phone
    identifier: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


# ---------------------------------------------------------
# PERMISSION MODELS
# ---------------------------------------------------------

class PermissionRead(BaseModel):
    id: int
    key: str
    label: str
    category: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------
# ROLE MODELS
# ---------------------------------------------------------

class RoleRead(BaseModel):
    id: int
    key: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = None

    class Config:
        from_attributes = True


class RoleWithPermissionsRead(BaseModel):
    id: int
    key: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = None
    permissions: List[PermissionRead] = []

    class Config:
        from_attributes = True


# ---------------------------------------------------------
# PROJECT MODELS
# ---------------------------------------------------------

class ProjectRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ProjectWithRoleSummary(BaseModel):
    project_id: UUID
    project_name: str
    description: Optional[str] = None
    status: Optional[str] = None
    role_key: Optional[str] = None
    role_name: Optional[str] = None

class ProjectAssistantRequest(BaseModel):
    message: str


class ProjectAssistantResponse(BaseModel):
    reply: str
    project_id: str
    user_message_id: str
    assistant_message_id: str
    run_id: str
    
class ProjectAssistantMessage(BaseModel):
    id: str
    role: str              # "user" or "assistant"
    content: str
    created_at: datetime | None = None
    
class ProjectAssistantHistoryResponse(BaseModel):
    messages: list[ProjectAssistantMessage]

# ---------------------------------------------------------
# Project Documents
# ---------------------------------------------------------    
    
class ProjectDocumentCreate(BaseModel):
    title: str
    content: str


class ProjectDocumentRead(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    content: str
    created_at: datetime
    created_by_id: UUID | None = None

    class Config:
        from_attributes = True    

# ---------------------------------------------------------
# INVITE CREATION (PM sends)
# ---------------------------------------------------------

class InviteCreateRequest(BaseModel):
    invitee_email: Optional[EmailStr] = None
    invitee_phone: Optional[str] = None


class InviteCreatedResponse(BaseModel):
    token: str
    project_id: UUID
    project_name: str
    invitee_email: Optional[EmailStr] = None
    invitee_phone: Optional[str] = None
    status: str


# ---------------------------------------------------------
# INVITE LOOKUP (invitee views)
# ---------------------------------------------------------

class InviteInfo(BaseModel):
    project_name: str
    project_id: UUID
    status: str
    invitee_email: Optional[EmailStr] = None
    invitee_phone: Optional[str] = None
    has_account: bool


# ---------------------------------------------------------
# INVITE ACCEPTANCE (invitee confirms)
# ---------------------------------------------------------

class InviteAcceptRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    password: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None


class InviteAcceptResponse(BaseModel):
    project_id: UUID
    project_name: str
    message: str


# ---------------------------------------------------------
# PM VIEW — INVITES AWAITING APPROVAL
# ---------------------------------------------------------

class InvitePendingForPM(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    invitee_user_id: Optional[UUID] = None
    invitee_name: Optional[str] = None
    invitee_email: Optional[EmailStr] = None
    invitee_phone: Optional[str] = None
    status: str
    accepted_at: Optional[datetime] = None


# ---------------------------------------------------------
# PM APPROVAL — ASSIGN ROLE
# ---------------------------------------------------------

class InviteApproveRequest(BaseModel):
    role_key: str  # e.g. "FOREMAN", "HOMEOWNER", etc.


class InviteApproveResponse(BaseModel):
    project_id: UUID
    project_name: str
    user_id: UUID
    role_key: str
    message: str


# ---------------------------------------------------------
# PROJECT MEMBERS
# ---------------------------------------------------------

class ProjectMemberRead(BaseModel):
    id: int
    project_id: UUID
    user_id: UUID
    role_key: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectMemberDetail(BaseModel):
    user_id: UUID
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    role_key: Optional[str] = None
    role_name: Optional[str] = None
