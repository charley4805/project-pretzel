import uuid
from datetime import datetime, date
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
    Float,
    Date,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.database import Base


# ---------- CORE USER / PROJECT MODELS ----------


class User(Base):
    __tablename__ = "users"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=True, index=True)
    phone_number = Column(String(20), unique=True, nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)

    password_hash = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    memberships = relationship("ProjectMember", back_populates="user")
    messages = relationship("Message", back_populates="sender")
    ai_runs = relationship("AIRunLog", back_populates="user")

    notifications = relationship("Notification", back_populates="user")

    sent_invites = relationship(
        "ProjectInvite",
        back_populates="inviter",
        foreign_keys="ProjectInvite.inviter_id",
    )
    received_invites = relationship(
        "ProjectInvite",
        back_populates="invitee_user",
        foreign_keys="ProjectInvite.invitee_user_id",
    )

    created_activities = relationship(
        "Activity",
        back_populates="created_by",
        cascade="all, delete-orphan",
    )

    audit_logs = relationship("AuditLog", back_populates="user")
    message_reads = relationship("MessageRead", back_populates="user")


class ProjectStatus(Base):
    """
    Normalized project status for dashboard:
    - ON_TRACK
    - CATCHING_UP
    - BEHIND
    - WAY_BEHIND
    """

    __tablename__ = "project_statuses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    label = Column(String(100), nullable=False)
    color_hex = Column(String(7), nullable=True)  # e.g. "#22c55e"
    sort_order = Column(Integer, default=0)

    projects = relationship("Project", back_populates="status_ref")


class Project(Base):
    __tablename__ = "projects"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # High-level status string
    status = Column(String(50), default="active")

    # Normalized status FK
    status_id = Column(Integer, ForeignKey("project_statuses.id"), nullable=True)
    status_ref = relationship("ProjectStatus", back_populates="projects")

    created_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    # 🔹 Project metadata
    project_type = Column(String(50), nullable=True)  # "NewBuild", "MajorRenovation", etc.
    end_date = Column(Date, nullable=True)            # target completion date

    # Location fields (for weather + mapping)
    address_line1 = Column(String(255), nullable=True)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Blocker / on-hold status (permits, inspections, etc.)
    is_blocked = Column(Boolean, nullable=False, default=False)
    blocker_reason = Column(Text, nullable=True)

    members = relationship("ProjectMember", back_populates="project")
    messages = relationship("Message", back_populates="project")
    ai_runs = relationship("AIRunLog", back_populates="project")

    invites = relationship(
        "ProjectInvite",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    notifications = relationship("Notification", back_populates="project")

    activity_schedules = relationship(
        "ActivitySchedule",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    check_ins = relationship(
        "MemberCheckIn",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    audit_logs = relationship(
        "AuditLog",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    documents = relationship(
        "ProjectDocument",
        back_populates="project",
        cascade="all, delete-orphan",
    )



# ---------- ROLES & PERMISSIONS ----------


class Permission(Base):
    """
    A single capability in the system, e.g.
    - project.create
    - project.manage_members
    - message.post
    - financials.view_budget
    """

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    category = Column(String(100), nullable=True)  # e.g. "Project", "Messaging"
    description = Column(Text, nullable=True)

    roles = relationship("RolePermission", back_populates="permission")


class Role(Base):
    """
    Business role in the construction project, like:
    - PROJECT_MANAGER
    - ARCHITECT
    - ENGINEER
    - FOREMAN
    - TRADE_PARTNER
    - HOMEOWNER
    """

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)

    members = relationship("ProjectMember", back_populates="role")
    permissions = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
    )


class RolePermission(Base):
    """
    Many-to-many link between Role and Permission.
    If `allowed` is true, role has that permission.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    allowed = Column(Boolean, nullable=False, default=True)

    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission", back_populates="roles")


class ProjectMember(Base):
    """
    Links a user to a project and assigns a Role.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="memberships")
    role = relationship("Role", back_populates="members")

    activity_schedules = relationship(
        "ActivitySchedule",
        back_populates="project_member",
        cascade="all, delete-orphan",
    )

    check_ins = relationship(
        "MemberCheckIn",
        back_populates="project_member",
        cascade="all, delete-orphan",
    )


# ---------- MESSAGING ----------


class Message(Base):
    __tablename__ = "messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    sender_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    content = Column(Text, nullable=False)
    message_type = Column(
        SAEnum("user", "assistant", "system", name="message_type_enum"),
        default="user",
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    project = relationship("Project", back_populates="messages")
    sender = relationship("User", back_populates="messages")

    attachments = relationship(
        "MessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    reads = relationship(
        "MessageRead",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageAttachment(Base):
    """
    File metadata for attachments on a message.
    Actual binary lives in object storage (S3, etc.).
    """

    __tablename__ = "message_attachments"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(PGUUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100), nullable=True)  # e.g. "image/png", "video/mp4"
    file_size = Column(Integer, nullable=True)      # bytes

    storage_url = Column(Text, nullable=False)      # pre-signed or public URL
    thumbnail_url = Column(Text, nullable=True)     # optional image thumb

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    message = relationship("Message", back_populates="attachments")


class MessageRead(Base):
    """
    Tracks which users have read which messages.
    Drives has_unread_messages on project cards.
    """

    __tablename__ = "message_reads"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_user_read"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(PGUUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    read_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    message = relationship("Message", back_populates="reads")
    user = relationship("User", back_populates="message_reads")


# ---------- AI RUNS ----------


class AIRunLog(Base):
    __tablename__ = "ai_run_logs"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    input_message = Column(Text, nullable=False)
    output_message = Column(Text, nullable=False)
    tools_used = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    project = relationship("Project", back_populates="ai_runs")
    user = relationship("User", back_populates="ai_runs")


class ProjectInvite(Base):
    """
    Invitation flow:
    - Created by a PM for a given project, via email/phone/QR.
    - Invitee lands on frontend with token.
    - They create an account (or log in), then accept.
    - PM later approves and assigns a Role.
    """

    __tablename__ = "project_invites"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    inviter_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    invitee_email = Column(String(255), nullable=True, index=True)
    invitee_phone = Column(String(20), nullable=True, index=True)

    token = Column(String(64), unique=True, nullable=False, index=True)

    status = Column(
        SAEnum("pending", "accepted", "cancelled", "expired", name="invite_status_enum"),
        default="pending",
        nullable=False,
    )

    invitee_user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="invites")
    inviter = relationship("User", foreign_keys=[inviter_id], back_populates="sent_invites")
    invitee_user = relationship("User", foreign_keys=[invitee_user_id], back_populates="received_invites")


class ProjectDocument(Base):
    __tablename__ = "project_documents"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)  # plain text RAG source
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    project = relationship("Project", back_populates="documents")
    created_by = relationship("User", back_populates="created_documents")


# Add reverse side for created_documents on User
User.created_documents = relationship(
    "ProjectDocument",
    back_populates="created_by",
    cascade="all, delete-orphan",
)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)

    # e.g. "completed_work", "new_message", "deadline", "weather_alert"
    type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)

    is_read = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )
    due_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="notifications")
    project = relationship("Project", back_populates="notifications")


# ---------- ACTIVITIES (CATALOG) & SCHEDULING ----------


class Activity(Base):
    __tablename__ = "activities"

    id = Column(
        PGUUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        default=uuid.uuid4,                  # Python-side default
        server_default=text("gen_random_uuid()"),  # DB-side default (see SQL below)
    )

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    is_custom = Column(Boolean, nullable=False, default=False)

    date_added = Column(
        DateTime(timezone=True),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    created_by_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_by = relationship("User", back_populates="created_activities")

    schedules = relationship(
        "ActivitySchedule",
        back_populates="activity",
        cascade="all, delete-orphan",
    )


class ActivityStatus(PyEnum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ActivitySchedule(Base):
    """
    Scheduling table tying activities to projects, with dates & status.
    """

    __tablename__ = "activity_schedules"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    activity_id = Column(PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False)
    project_member_id = Column(Integer, ForeignKey("project_members.id"), nullable=True)

    # Scheduling window
    scheduled_start_date = Column(Date, nullable=False)
    scheduled_end_date = Column(Date, nullable=True)

    # Actuals
    actual_start_date = Column(Date, nullable=True)
    actual_end_date = Column(Date, nullable=True)

    status = Column(
        SAEnum(ActivityStatus, name="activity_schedule_status_enum"),
        nullable=False,
        default=ActivityStatus.PLANNED,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        # onupdate could be added here if desired
    )

    project = relationship("Project", back_populates="activity_schedules")
    activity = relationship("Activity", back_populates="schedules")

    # This is the key relationship that pairs with ProjectMember.activity_schedules
    project_member = relationship("ProjectMember", back_populates="activity_schedules")

    check_ins = relationship("MemberCheckIn", back_populates="activity_schedule")


class MemberCheckIn(Base):
    """
    Tracks when a member is on-site for a project (optionally tied to a scheduled activity).
    """

    __tablename__ = "member_checkins"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    project_member_id = Column(Integer, ForeignKey("project_members.id"), nullable=False)

    activity_schedule_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("activity_schedules.id"),
        nullable=True,
    )

    check_in_time = Column(DateTime(timezone=True), nullable=False)
    check_out_time = Column(DateTime(timezone=True), nullable=True)

    notes = Column(Text, nullable=True)

    project = relationship("Project", back_populates="check_ins")
    project_member = relationship("ProjectMember", back_populates="check_ins")
    activity_schedule = relationship("ActivitySchedule", back_populates="check_ins")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)

    action = Column(String(100), nullable=False)       # e.g. "PROJECT_CREATED"
    entity_type = Column(String(50), nullable=False)   # e.g. "Project", "Activity"
    entity_id = Column(String(50), nullable=False)     # generic string ID

    # Use metadata_json as Python attr, but DB column name "metadata" is fine
    metadata_json = Column("metadata", JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    user = relationship("User", back_populates="audit_logs")
    project = relationship("Project", back_populates="audit_logs")
