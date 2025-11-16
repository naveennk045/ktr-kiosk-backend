"""Add KOT and KDS fields and kot_counters table

Revision ID: 20251116_kot_kds
Revises: <put_previous_revision_id_here>
Create Date: 2025-11-16 11:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20251116_kot_kds"
down_revision = "<put_previous_revision_id_here>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Create enum type for KDS status in DB if not exists
    kds_status_enum = postgresql.ENUM(
        "NOT_POSTED",
        "PENDING",
        "POSTED",
        "FAILED",
        name="kds_status_enum",
    )
    kds_status_enum.create(bind, checkfirst=True)

    # 2) Add new columns to orders (nullable for now so we can backfill)
    op.add_column("orders", sa.Column("kot_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("kot_number", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("kot_code", sa.String(), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "kds_status",
            kds_status_enum,
            nullable=True,  # temporarily nullable
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "kds_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("kds_last_error", sa.String(), nullable=True),
    )

    # 3) Create kot_counters table
    op.create_table(
        "kot_counters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kot_date", sa.Date(), nullable=False, unique=True),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_kot_counters_kot_date", "kot_counters", ["kot_date"], unique=True
    )

    # 4) BACKFILL EXISTING DATA ON orders -----------------------

    # Use raw SQL via connection
    # 4.a) Set kot_date from created_at (or today if created_at is null)
    bind.execute(
        sa.text(
            """
            UPDATE orders
            SET kot_date = COALESCE(created_at::date, NOW()::date)
            WHERE kot_date IS NULL
            """
        )
    )

    # 4.b) Assign kot_number per day based on id ordering
    #      (1,2,3,... per kot_date)
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    kot_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY kot_date
                        ORDER BY id
                    ) AS rn
                FROM orders
                WHERE kot_number IS NULL
            )
            UPDATE orders o
            SET kot_number = r.rn
            FROM ranked r
            WHERE o.id = r.id
            """
        )
    )

    # 4.c) Generate kot_code = 'ktr-' || kot_number
    bind.execute(
        sa.text(
            """
            UPDATE orders
            SET kot_code = 'ktr-' || kot_number
            WHERE kot_code IS NULL
            """
        )
    )

    # 4.d) Initialize kds_status from existing kds_invoice_id
    bind.execute(
        sa.text(
            """
            UPDATE orders
            SET kds_status =
                CASE
                    WHEN kds_invoice_id IS NOT NULL THEN 'POSTED'::kds_status_enum
                    ELSE 'NOT_POSTED'::kds_status_enum
                END
            WHERE kds_status IS NULL
            """
        )
    )

    # 5) ENFORCE CONSTRAINTS AND INDEXES -----------------------

    # Unique KOT per day
    op.create_unique_constraint(
        "uq_orders_kot_per_day",
        "orders",
        ["kot_date", "kot_number"],
    )

    # Make required fields NOT NULL
    op.alter_column("orders", "kot_date", nullable=False)
    op.alter_column("orders", "kot_number", nullable=False)
    op.alter_column("orders", "kot_code", nullable=False)
    op.alter_column("orders", "kds_status", nullable=False)

    # Helpful indexes on orders
    op.create_index("ix_orders_kot_code", "orders", ["kot_code"])
    op.create_index("ix_orders_kot_date", "orders", ["kot_date"])
    op.create_index("ix_orders_kds_status", "orders", ["kds_status"])


def downgrade() -> None:
    bind = op.get_bind()

    # Drop indexes and constraints first
    op
