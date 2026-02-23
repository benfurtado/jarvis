"""
Jarvis Deploy Tool — deploy static sites + stop services.
"""
import os
import json
import logging

from langchain_core.tools import tool

from app.services import start_service, stop_service, list_services, get_public_ip

logger = logging.getLogger("Jarvis")


@tool
def deploy_static_site(name: str, directory: str, port: int, html: str) -> str:
    """
    Deploy a static website. Creates directory, writes index.html, starts HTTP server, returns URL.
    Args:
        name: Site name identifier (e.g., 'coffeesite').
        directory: Absolute path for the site files.
        port: Port number to serve on (e.g., 3433).
        html: Full HTML content for index.html.
    """
    logger.info(f"Deploying static site '{name}' at {directory} on port {port}")

    try:
        # Create directory
        os.makedirs(directory, exist_ok=True)

        # Write index.html
        index_path = os.path.join(directory, "index.html")
        with open(index_path, "w") as f:
            f.write(html)

        # Start HTTP server
        result = start_service(name, directory, port)

        if result["status"] == "running":
            return (
                f"Site '{name}' deployed successfully!\n"
                f"URL: {result['url']}\n"
                f"Directory: {directory}\n"
                f"Port: {port}\n"
                f"PID: {result['pid']}\n"
                f"index.html written ({len(html)} bytes)"
            )
        elif result["status"] == "already_running":
            # Re-write HTML anyway
            return (
                f"Site '{name}' is already running.\n"
                f"URL: {result['url']}\n"
                f"Updated index.html ({len(html)} bytes)\n"
                f"PID: {result['pid']}"
            )
        else:
            return f"Deploy failed: {result.get('message', 'Unknown error')}"

    except Exception as e:
        logger.error(f"Deploy error: {e}")
        return f"Deploy error: {str(e)}"


@tool
def stop_deployed_service(name: str) -> str:
    """
    Stop a deployed site/service by name.
    Args:
        name: The service name to stop (e.g., 'coffeesite').
    """
    result = stop_service(name)
    if result["status"] == "stopped":
        return f"Service '{name}' stopped successfully."
    else:
        return f"Error: {result.get('message', 'Unknown error')}"


@tool
def list_deployed_services() -> str:
    """
    List all currently running deployed sites/services with their URLs.
    """
    services = list_services()
    if not services:
        return "No active services running."

    output = f"Active Services ({len(services)}):\n\n"
    for s in services:
        output += f"  {s['name']}\n"
        output += f"    URL: {s['url']}\n"
        output += f"    PID: {s['pid']}\n"
        output += f"    Dir: {s['directory']}\n\n"
    return output
