import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
    Float,
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

    # Notifications for this user
    notifications = relationship("Notification", back_populates="user")

    # Optional: invites they sent / received (used by ProjectInvite)
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


class Project(Base):
    __tablename__ = "projects"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")
    created_by_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    # 🔹 Location fields (for weather + mapping)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # 🔹 Blocker / on-hold status (permits, inspections, etc.)
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

    # Notifications scoped to this project
    notifications = relationship("Notification", back_populates="project")


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
    category = Column(String(100), nullable=True)  # e.g. "Project", "Messaging", "Financials"
    description = Column(Text, nullable=True)

    roles = relationship("RolePermission", back_populates="permission")


class Role(Base):
    """
    A business role in the construction project, like:
    - PROJECT_MANAGER
    - ARCHITECT
    - ENGINEER
    - FOREMAN
    - TRADE_PARTNER
    - HOMEOWNER
    """

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)  # machine key: "PROJECT_MANAGER"
    name = Column(String(100), nullable=False)  # human label: "Project Manager"
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


class Message(Base):
    __tablename__ = "messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    sender_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    content = Column(Text, nullable=False)
    message_type = Column(
        Enum("user", "assistant", "system", name="message_type_enum"),
        default="user",
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    project = relationship("Project", back_populates="messages")
    sender = relationship("User", back_populates="messages")


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
        Enum("pending", "accepted", "cancelled", "expired", name="invite_status_enum"),
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

    project = relationship("Project", backref="documents")
    created_by = relationship("User", backref="created_documents")


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