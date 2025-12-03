"""Add project metadata fields: address line1/2, project_type, end_date

Revision ID: 20251202_add_project_metadata
Revises: 9bc3f0563d89_add_activities_schedules_checkins_audit_
Create Date: 2025-12-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251202"
down_revision: Union[str, None] = "9bc3f0563d89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add new columns to projects ---
    op.add_column(
        "projects",
        sa.Column("address_line1", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("address_line2", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("project_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    # Reverse in the opposite order
    op.drop_column("projects", "end_date")
    op.drop_column("projects", "project_type")
    op.drop_column("projects", "address_line2")
    op.drop_column("projects", "address_line1")
