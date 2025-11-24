from sqlalchemy.orm import Session

from .database import SessionLocal, engine, Base
from . import models

# Ensure tables exist (for safety in dev)
Base.metadata.create_all(bind=engine)


def seed_roles_and_permissions(db: Session):
    # --- Define permissions ---
    permissions = [
        # Project-level
        ("project.create", "Create projects", "Project"),
        ("project.view", "View project details", "Project"),
        ("project.update", "Edit project details", "Project"),
        ("project.archive", "Archive / close projects", "Project"),

        # Membership
        ("member.manage", "Invite/remove project members", "Membership"),
        ("member.assign_roles", "Assign roles to members", "Membership"),

        # Messaging
        ("message.read_all", "Read all project messages", "Messaging"),
        ("message.post", "Post messages", "Messaging"),
        ("message.delete_own", "Delete own messages", "Messaging"),

        # Docs / tools
        ("docs.view", "View project documents", "Docs"),
        ("docs.upload", "Upload project documents", "Docs"),
        ("tools.ai_use", "Use AI assistant on project", "Tools"),

        # Financials / bids
        ("financials.view_budget", "View original budgets / estimates", "Financials"),
        ("financials.edit_budget", "Edit budgets / estimates", "Financials"),
        ("bids.view", "View trade bids", "Financials"),
        ("bids.approve", "Approve bids / selections", "Financials"),
    ]

    key_to_perm = {}
    for key, label, category in permissions:
        perm = (
            db.query(models.Permission)
            .filter(models.Permission.key == key)
            .first()
        )
        if not perm:
            perm = models.Permission(
                key=key,
                label=label,
                category=category,
                description=None,
            )
            db.add(perm)
        key_to_perm[key] = perm

    # --- Define roles ---
    roles = [
        ("PROJECT_MANAGER", "Project Manager", "Owns the project, full control", 10),
        ("ARCHITECT", "Architect", "Design and plans, limited admin", 20),
        ("ENGINEER", "Engineer", "Structural / civil / MEP coordination", 30),
        ("FOREMAN", "Construction Foreman", "Runs day-to-day site work", 40),
        ("ESTIMATOR", "Estimator", "Handles takeoffs and budgets", 50),
        ("SURVEYOR", "Surveyor", "Site layout and measurements", 60),
        ("TRADE_PARTNER", "Trade Partner / Vendor", "External trade or vendor", 70),
        ("HOMEOWNER", "Homeowner / Client", "Client-facing view only", 80),
    ]

    key_to_role = {}
    for key, name, desc, sort_order in roles:
        role = (
            db.query(models.Role)
            .filter(models.Role.key == key)
            .first()
        )
        if not role:
            role = models.Role(
                key=key,
                name=name,
                description=desc,
                sort_order=sort_order,
            )
            db.add(role)
        key_to_role[key] = role

    db.flush()  # ensure ids

    # --- Role → permissions mapping ---
    def allow(role_key: str, perm_keys):
        role = key_to_role[role_key]
        for p_key in perm_keys:
            perm = key_to_perm[p_key]
            existing = (
                db.query(models.RolePermission)
                .filter(
                    models.RolePermission.role_id == role.id,
                    models.RolePermission.permission_id == perm.id,
                )
                .first()
            )
            if not existing:
                db.add(
                    models.RolePermission(
                        role_id=role.id,
                        permission_id=perm.id,
                        allowed=True,
                    )
                )

    # PM: basically everything
    allow(
        "PROJECT_MANAGER",
        [
            "project.create", "project.view", "project.update", "project.archive",
            "member.manage", "member.assign_roles",
            "message.read_all", "message.post", "message.delete_own",
            "docs.view", "docs.upload",
            "tools.ai_use",
            "financials.view_budget", "financials.edit_budget",
            "bids.view", "bids.approve",
        ],
    )

    # Architect: project view/update, docs, AI, messaging
    allow(
        "ARCHITECT",
        [
            "project.view", "project.update",
            "message.read_all", "message.post", "message.delete_own",
            "docs.view", "docs.upload",
            "tools.ai_use",
        ],
    )

    # Engineer: similar to Architect but no project.update
    allow(
        "ENGINEER",
        [
            "project.view",
            "message.read_all", "message.post", "message.delete_own",
            "docs.view",
            "tools.ai_use",
        ],
    )

    # Foreman: site-focused; messaging + docs
    allow(
        "FOREMAN",
        [
            "project.view",
            "message.read_all", "message.post", "message.delete_own",
            "docs.view", "docs.upload",
            "tools.ai_use",
        ],
    )

    # Estimator: heavy on financials
    allow(
        "ESTIMATOR",
        [
            "project.view",
            "financials.view_budget", "financials.edit_budget",
            "bids.view",
            "tools.ai_use",
        ],
    )

    # Surveyor: mostly view + docs
    allow(
        "SURVEYOR",
        [
            "project.view",
            "docs.view",
            "message.post",
            "tools.ai_use",
        ],
    )

    # Trade Partner / Vendor
    allow(
        "TRADE_PARTNER",
        [
            "project.view",
            "message.post",
            "docs.view", "docs.upload",
            "bids.view",
            "tools.ai_use",
        ],
    )

    # Homeowner: very limited, read-only
    allow(
        "HOMEOWNER",
        [
            "project.view",
            "message.read_all",
            "docs.view",
            "tools.ai_use",
        ],
    )

    db.commit()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
        print("Roles and permissions seeded.")
    finally:
        db.close()
