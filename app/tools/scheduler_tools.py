"""
Jarvis Task Scheduler — cron-like scheduled command execution.
Uses APScheduler with SQLite backing.
"""
import subprocess
import shlex
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from langchain_core.tools import tool

logger = logging.getLogger("Jarvis")

# Global scheduler instance
_scheduler = None
_db = None


def init_scheduler(app, db_instance):
    """Initialize the APScheduler and load persisted tasks."""
    global _scheduler, _db
    _db = db_instance

    _scheduler = BackgroundScheduler()
    _scheduler.start()

    # Load active tasks from DB
    tasks = _db.get_scheduled_tasks(active_only=True)
    for task in tasks:
        try:
            _add_job(task["id"], task["command"], task["cron_expression"])
            logger.info(f"Loaded scheduled task: {task['id']}")
        except Exception as e:
            logger.error(f"Failed to load task {task['id']}: {e}")

    logger.info(f"Scheduler initialized with {len(tasks)} active tasks.")


def _add_job(task_id: str, command: str, cron_expr: str):
    """Add a job to APScheduler."""
    # Parse cron expression: "minute hour day month day_of_week"
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr}. Expected 5 fields.")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    _scheduler.add_job(
        _execute_scheduled_command,
        trigger=trigger,
        args=[task_id, command],
        id=task_id,
        replace_existing=True,
    )


def _execute_scheduled_command(task_id: str, command: str):
    """Execute a scheduled command and log the result."""
    logger.info(f"Scheduled task {task_id} executing: {command}")
    try:
        parts = shlex.split(command)
        result = subprocess.run(parts, capture_output=True, text=True, timeout=60)
        output = result.stdout[:500] if result.stdout else "(no output)"
        logger.info(f"Scheduled task {task_id} completed. Exit code: {result.returncode}")
    except Exception as e:
        logger.error(f"Scheduled task {task_id} failed: {e}")

    if _db:
        _db.update_task_last_run(task_id)


@tool
def schedule_task(command: str, cron_expr: str) -> str:
    """
    Schedule a command to run on a cron-like schedule.
    Args:
        command: The shell command to execute.
        cron_expr: Cron expression with 5 fields (minute hour day month day_of_week).
                   Example: '0 */6 * * *' for every 6 hours.
    """
    logger.info(f"Scheduling task: command='{command}', cron='{cron_expr}'")
    if not _db or not _scheduler:
        return "Scheduler not initialized."

    try:
        task_id = _db.create_scheduled_task(
            user_id="system",
            command=command,
            cron_expression=cron_expr,
        )
        _add_job(task_id, command, cron_expr)
        return f"Task scheduled successfully.\nID: {task_id}\nCommand: {command}\nSchedule: {cron_expr}"
    except Exception as e:
        return f"Error scheduling task: {str(e)}"


@tool
def list_scheduled_tasks() -> str:
    """
    List all active scheduled tasks.
    """
    if not _db:
        return "Scheduler not initialized."

    tasks = _db.get_scheduled_tasks(active_only=True)
    if not tasks:
        return "No active scheduled tasks."

    output = f"Active Scheduled Tasks ({len(tasks)}):\n\n"
    for t in tasks:
        output += f"  ID: {t['id']}\n"
        output += f"  Command: {t['command']}\n"
        output += f"  Schedule: {t['cron_expression']}\n"
        output += f"  Last Run: {t['last_run'] or 'Never'}\n"
        output += f"  Created: {t['created_at']}\n"
        output += "-" * 30 + "\n"
    return output


@tool
def cancel_scheduled_task(task_id: str) -> str:
    """
    Cancel/deactivate a scheduled task.
    Args:
        task_id: The ID of the task to cancel.
    """
    if not _db or not _scheduler:
        return "Scheduler not initialized."

    try:
        _db.deactivate_scheduled_task(task_id)
        try:
            _scheduler.remove_job(task_id)
        except Exception:
            pass  # Job might not exist in scheduler
        return f"Scheduled task {task_id} has been cancelled."
    except Exception as e:
        return f"Error cancelling task: {str(e)}"
