from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------
# USER MODELS
# ---------------------------------------------------------


class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None


class UserCreate(UserBase):
    """
    Generic create model for admin/system-created users.
    Registration flow can still use UserRegisterRequest.
    """
    password: str
    is_active: Optional[bool] = True


class UserUpdate(BaseModel):
    """
    Partial update model for user profile / admin updates.
    All fields optional so it works for PATCH-style endpoints.
    """
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


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


class PermissionBase(BaseModel):
    key: str
    label: str
    category: Optional[str] = None
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    """
    Create model for permissions.
    """
    pass


class PermissionUpdate(BaseModel):
    """
    Partial update model for permissions.
    """
    key: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


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


class RoleBase(BaseModel):
    key: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = None


class RoleCreate(RoleBase):
    """
    Create model for roles.
    """
    pass


class RoleUpdate(BaseModel):
    """
    Partial update model for roles.
    """
    key: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


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
    permissions: List[PermissionRead] = Field(default_factory=list)

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

    # 🔹 Location info (for display + weather)
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        from_attributes = True


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None

    # User-entered address fields
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    # ❌ No latitude/longitude here – backend will compute them


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None

    status: Optional[str] = None
    project_type: Optional[str] = None

    # Accept a few shapes, but we normalize later
    end_date: Optional[date | datetime | str] = None


# Optional aliases if you want to think in CRUD terms
ProjectCreate = ProjectCreateRequest
ProjectUpdate = ProjectUpdateRequest


# -------- Today’s activities summary for project cards --------


class ProjectActivityTodaySummary(BaseModel):
    id: UUID
    title: str
    member_name: Optional[str] = None
    member_on_site: bool = False


class ProjectWithRoleSummary(BaseModel):
    project_id: UUID
    project_name: str
    description: Optional[str] = None
    status: Optional[str] = None
    role_key: Optional[str] = None
    role_name: Optional[str] = None

    # 🔹 Location info for dashboard / project cards
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # 🔹 Dashboard extras
    completion_percentage: float = 0.0
    has_unread_messages: bool = False
    todays_activities: List[ProjectActivityTodaySummary] = Field(default_factory=list)
    
    project_type: Optional[str] = None
    end_date: Optional[date] = None

    is_owner: bool = False


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


class ProjectIntakeCreate(BaseModel):
    address: dict
    zoning_precheck: Optional[dict] = None
    project_type: str
    project_name_suggested: str
    project_name_final: str
    intake_method: str
    timeline_docs_uploaded: Optional[bool] = None
    restraints_docs_uploaded: Optional[bool] = None
    notes: Optional[str] = None


# ---------------------------------------------------------
# Project Documents
# ---------------------------------------------------------


class ProjectDocumentBase(BaseModel):
    title: str
    content: str  # plain text RAG source


class ProjectDocumentCreate(BaseModel):
    title: str
    content: str


class ProjectDocumentUpdate(BaseModel):
    """
    Partial update model for project documents.
    """
    title: Optional[str] = None
    content: Optional[str] = None


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
# ACTIVITIES
# ---------------------------------------------------------


class ActivityCreate(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_date: date
    project_member_id: Optional[int] = None


class ActivityUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[date] = None
    status: Optional[str] = None  # SCHEDULED, IN_PROGRESS, COMPLETED, etc.


class ActivityRead(BaseModel):
    id: UUID
    project_id: UUID
    project_member_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    scheduled_date: date
    status: Optional[str] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ---------------------------------------------------------
# ACTIVITY CATALOG + SCHEDULING
# ---------------------------------------------------------

class ActivityDefinitionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ActivityDefinitionRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_custom: bool
    date_added: datetime

    class Config:
        from_attributes = True


class ActivityScheduleItemCreate(BaseModel):
    activity_id: UUID
    project_member_id: Optional[int] = None
    scheduled_start_date: date
    scheduled_end_date: Optional[date] = None


class ActivityScheduleRead(BaseModel):
    id: UUID
    project_id: UUID
    activity_id: UUID
    activity_name: str
    description: Optional[str] = None
    project_member_id: Optional[int] = None

    scheduled_start_date: date
    scheduled_end_date: Optional[date] = None
    actual_start_date: Optional[date] = None
    actual_end_date: Optional[date] = None
    status: Optional[str] = None
    
class ActivityCatalogItem(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_custom: Optional[bool] = False    


class ActivityCreatePayload(BaseModel):

    activity_id: Optional[UUID] = None   
    title: str
    description: Optional[str] = None
    scheduled_date: date
    project_member_id: Optional[int] = None


class ActivityUpdatePayload(BaseModel):

    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[date] = None
    status: Optional[str] = None   # "PLANNED", "SCHEDULED", "COMPLETED", etc.    
    
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


class ProjectMemberCreate(BaseModel):
    project_id: UUID
    user_id: UUID
    role_key: Optional[str] = None


class ProjectMemberUpdate(BaseModel):
    role_key: Optional[str] = None


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


# ---------------------------------------------------------
# PROJECT MESSAGES (human chat)
# ---------------------------------------------------------


class MessageAttachmentRead(BaseModel):
    id: UUID
    file_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    storage_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectMessageRead(BaseModel):
    id: UUID
    project_id: UUID
    sender_id: Optional[UUID] = None
    sender_name: Optional[str] = None
    content: str
    message_type: str
    created_at: datetime
    attachments: List[MessageAttachmentRead] = Field(default_factory=list)


class ProjectMessageCreate(BaseModel):
    content: str
    # Attachments will be handled via a separate upload flow later.
