"""
Jarvis Tools — exports ALL_TOOLS for LangGraph.
"""
from app.tools.terminal import run_terminal_command
from app.tools.screenshot import take_screenshot
from app.tools.gmail import send_email, fetch_emails, classify_and_process_emails
from app.tools.social import send_social_message, check_social_status
from app.tools.website import download_website
from app.tools.system_monitor import system_monitor
from app.tools.file_manager import list_directory, download_file, upload_file, search_files
from app.tools.scheduler_tools import schedule_task, list_scheduled_tasks, cancel_scheduled_task
from app.tools.notifications import send_telegram_notification
from app.tools.deploy import deploy_static_site, stop_deployed_service, list_deployed_services

ALL_TOOLS = [
    # Core
    run_terminal_command,
    take_screenshot,
    # Email
    send_email,
    fetch_emails,
    classify_and_process_emails,
    # Social
    send_social_message,
    check_social_status,
    # Web
    download_website,
    deploy_static_site,
    stop_deployed_service,
    list_deployed_services,
    # System
    system_monitor,
    # Files
    list_directory,
    download_file,
    upload_file,
    search_files,
    # Scheduler
    schedule_task,
    list_scheduled_tasks,
    cancel_scheduled_task,
    # Notifications
    send_telegram_notification,
]
