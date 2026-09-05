"""Database-side aggregates; dashboards never load every task and issue."""

from sqlalchemy import select, func, union_all
from app.models.project import Project
from app.models.audit import AuditTask, AuditIssue
from app.models.agent_task import AgentTask, AgentFinding


async def project_stats(db, user_id):
    projects = select(Project.id).where(Project.owner_id == user_id)
    total_projects, active_projects = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Project.is_active.is_(True)),
            )
            .select_from(Project)
            .where(Project.owner_id == user_id)
        )
    ).one()
    tasks = union_all(
        *[
            select(model.status.label("status"), model.quality_score.label("score")).where(
                model.project_id.in_(projects)
            )
            for model in (AuditTask, AgentTask)
        ]
    ).subquery()
    total_tasks, completed_tasks, average = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(tasks.c.status == "completed"),
                func.avg(tasks.c.score).filter(
                    (tasks.c.status == "completed") & (tasks.c.score > 0)
                ),
            ).select_from(tasks)
        )
    ).one()
    issues = union_all(
        select(
            AuditIssue.issue_type.label("kind"), (AuditIssue.status == "resolved").label("resolved")
        ).where(
            AuditIssue.task_id.in_(select(AuditTask.id).where(AuditTask.project_id.in_(projects)))
        ),
        select(
            AgentFinding.vulnerability_type.label("kind"),
            AgentFinding.status.in_(["fixed", "wont_fix", "false_positive"]).label("resolved"),
        ).where(
            AgentFinding.task_id.in_(select(AgentTask.id).where(AgentTask.project_id.in_(projects)))
        ),
    ).subquery()
    total_issues, resolved_issues = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(issues.c.resolved.is_(True)),
            ).select_from(issues)
        )
    ).one()
    issue_types = dict(
        (await db.execute(select(issues.c.kind, func.count()).group_by(issues.c.kind))).all()
    )
    return dict(
        total_projects=total_projects,
        active_projects=active_projects,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        total_issues=total_issues,
        resolved_issues=resolved_issues,
        avg_quality_score=float(average or 0),
        issue_types=issue_types,
    )
