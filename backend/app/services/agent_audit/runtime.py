"""State local to one isolated audit worker process."""

_running_tasks = {}
_running_asyncio_tasks = {}
_running_orchestrators = {}
_running_event_managers = {}
_cancelled_tasks = set()


def is_task_cancelled(task_id):
    return task_id in _cancelled_tasks
