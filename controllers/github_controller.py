from fastapi import HTTPException, BackgroundTasks
from utils.github_api import GitHubAPI
import io
from typing import Optional, Dict, Tuple
import asyncio
import time
import uuid
import os
import logging
import base64

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store for background tasks and files
# This is necessary for Vercel which has an ephemeral filesystem
running_tasks: Dict[str, Dict] = {}
completed_tasks: Dict[str, Dict] = {}
file_storage: Dict[str, bytes] = {}  # Store file data in memory

async def download_folder_as_zip(owner: str, repo: str, folder_path: str, token: Optional[str] = None) -> tuple[io.BytesIO, str]:
    """Controller function to handle downloading a folder as a ZIP file"""
    try:
        # Initialize GitHub API with optional token
        github_api = GitHubAPI(token)
        
        # Create ZIP file from the specified folder
        zip_buffer = await github_api.create_zip_from_folder(owner, repo, folder_path)
        
        # Create a meaningful filename for the download
        folder_name = folder_path.strip('/').split('/')[-1] if folder_path.strip('/') else repo
        filename = f"{owner}_{repo}_{folder_name}.zip"
        
        return zip_buffer, filename
        
    except Exception as e:
        error_message = str(e)
        status_code = 500
        
        # Set specific status codes based on error message
        if "Authentication failed" in error_message:
            status_code = 401
        elif "API rate limit exceeded" in error_message:
            status_code = 429
        elif "Repository or path not found" in error_message:
            status_code = 404
        elif "insufficient permissions" in error_message:
            status_code = 403
            
        raise HTTPException(status_code=status_code, detail=error_message)

async def start_background_download(owner: str, repo: str, folder_path: str, token: Optional[str] = None) -> str:
    """Start a background task to download a folder as a ZIP file"""
    task_id = str(uuid.uuid4())
    
    # Create task info
    task_info = {
        'id': task_id,
        'owner': owner,
        'repo': repo,
        'folder_path': folder_path,
        'status': 'queued',
        'created_at': time.time(),
        'progress': 0,
        'result': None,
        'error': None
    }
    
    # Store task in running tasks
    running_tasks[task_id] = task_info
    
    # Create and run the background task
    asyncio.create_task(_execute_download_task(task_id, owner, repo, folder_path, token))
    
    return task_id

async def _execute_download_task(task_id: str, owner: str, repo: str, folder_path: str, token: Optional[str] = None):
    """Execute the ZIP download task in the background"""
    task_info = running_tasks[task_id]
    task_info['status'] = 'running'
    
    try:
        # Initialize GitHub API with optional token
        github_api = GitHubAPI(token)
        
        # Create ZIP file from the specified folder
        zip_buffer = await github_api.create_zip_from_folder(owner, repo, folder_path)
        
        # Create a meaningful filename for the download
        folder_name = folder_path.strip('/').split('/')[-1] if folder_path.strip('/') else repo
        filename = f"{owner}_{repo}_{folder_name}.zip"
        
        # Move the task to completed tasks
        task_info['status'] = 'completed'
        task_info['completed_at'] = time.time()
        task_info['progress'] = 100
        
        # Get the raw bytes data
        zip_data = zip_buffer.getvalue()
        
        task_info['result'] = {
            'filename': filename,
            'size': len(zip_data),
            'task_id': task_id
        }
        
        # Store the ZIP file data in memory instead of on disk
        # This is compatible with Vercel's ephemeral filesystem
        file_storage[task_id] = zip_data
        
        # Move from running to completed
        completed_tasks[task_id] = task_info
        
    except Exception as e:
        logger.error(f"Error in background task {task_id}: {str(e)}")
        task_info['status'] = 'failed'
        task_info['error'] = str(e)
        task_info['completed_at'] = time.time()
        
        # Move from running to completed (even though it failed)
        completed_tasks[task_id] = task_info
    
    finally:
        # Clean up running tasks
        if task_id in running_tasks:
            del running_tasks[task_id]

def get_task_status(task_id: str) -> Dict:
    """Get the status of a background task"""
    if task_id in running_tasks:
        return running_tasks[task_id]
    elif task_id in completed_tasks:
        return completed_tasks[task_id]
    else:
        raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")

def get_download_file(task_id: str) -> Tuple[io.BytesIO, str]:
    """Get the file data and filename for a completed download task"""
    if task_id in completed_tasks and completed_tasks[task_id]['status'] == 'completed':
        task_info = completed_tasks[task_id]
        if 'result' in task_info and 'filename' in task_info['result']:
            if task_id in file_storage:
                # Get the file data from memory
                file_data = file_storage[task_id]
                # Create a BytesIO object from the data
                file_stream = io.BytesIO(file_data)
                return file_stream, task_info['result']['filename']
    
    raise HTTPException(status_code=404, detail=f"Completed download for task {task_id} not found")

# Add a task cleanup function that runs periodically
async def cleanup_old_tasks():
    """Clean up old tasks and files to prevent memory leaks"""
    while True:
        try:
            current_time = time.time()
            # Get the maximum age from environment or default to 24 hours
            max_age_hours = float(os.getenv("TASK_CLEANUP_HOURS", "24"))
            max_age_seconds = max_age_hours * 3600
            
            # Clean up completed tasks older than max_age
            task_ids_to_remove = []
            for task_id, task in completed_tasks.items():
                if current_time - task.get('completed_at', current_time) > max_age_seconds:
                    task_ids_to_remove.append(task_id)
            
            # Remove the tasks and their file data
            for task_id in task_ids_to_remove:
                del completed_tasks[task_id]
                if task_id in file_storage:
                    del file_storage[task_id]
            
            if task_ids_to_remove:
                logger.info(f"Cleaned up {len(task_ids_to_remove)} old tasks")
                
            # Wait for some time before checking again
            await asyncio.sleep(3600)  # Check every hour
        except Exception as e:
            logger.error(f"Error in task cleanup: {str(e)}")
            await asyncio.sleep(3600)  # Wait and try again
