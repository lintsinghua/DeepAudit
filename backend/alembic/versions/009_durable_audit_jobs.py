"""Durable audit delivery and bounded list query indexes."""
from alembic import op
import sqlalchemy as sa

revision = "009_durable_audit_jobs"
down_revision = "008_add_files_with_findings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("checkpoint", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_jobs_delivery", "audit_jobs", ["status", "lease_until", "created_at"])
    op.create_index("ix_tasks_project_created", "audit_tasks", ["project_id", "created_at", "id"])
    op.create_index("ix_issues_task_created", "audit_issues", ["task_id", "created_at", "id"])
    op.create_index("ix_events_task_sequence", "agent_events", ["task_id", "sequence"])
    # Pre-queue releases may have left tasks pending/running during an upgrade.
    # Delivery reuses their persisted scan configuration and project data.
    op.execute("""INSERT INTO audit_jobs (id, kind)
        SELECT id, 'agent' FROM agent_tasks
        WHERE status NOT IN ('completed', 'failed', 'cancelled', 'paused')""")
    op.execute("""INSERT INTO audit_jobs (id, kind)
        SELECT id, CASE WHEN task_type = 'zip_upload' THEN 'zip' ELSE 'repository' END
        FROM audit_tasks WHERE status IN ('pending', 'running')""")


def downgrade():
    op.drop_index("ix_events_task_sequence", table_name="agent_events")
    op.drop_index("ix_issues_task_created", table_name="audit_issues")
    op.drop_index("ix_tasks_project_created", table_name="audit_tasks")
    op.drop_table("audit_jobs")
