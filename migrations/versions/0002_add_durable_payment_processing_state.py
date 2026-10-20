"""Add durable payment processing state"""

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("processing_failures", sa.Integer(), server_default="0", nullable=False))
    op.add_column("payments", sa.Column("webhook_sent_at", sa.DateTime(), nullable=True))
    op.add_column("payments", sa.Column("dead_lettered_at", sa.DateTime(), nullable=True))
    op.create_check_constraint("ck_payments_processing_failures", "payments", "processing_failures BETWEEN 0 AND 3")
    op.create_check_constraint(
        "ck_payments_webhook_status", "payments",
        "webhook_sent_at IS NULL OR status IN ('succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_payments_delivery_result", "payments",
        "webhook_sent_at IS NULL OR dead_lettered_at IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payments_delivery_result", "payments", type_="check")
    op.drop_constraint("ck_payments_webhook_status", "payments", type_="check")
    op.drop_constraint("ck_payments_processing_failures", "payments", type_="check")
    op.drop_column("payments", "dead_lettered_at")
    op.drop_column("payments", "webhook_sent_at")
    op.drop_column("payments", "processing_failures")
