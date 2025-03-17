from fastapi import APIRouter, Query, Depends, HTTPException, Header, BackgroundTasks, Path
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from controllers.github_controller import (
    download_folder_as_zip, 
    start_background_download,
    get_task_status,
    get_download_file
)
from typing import Optional, Dict
import os

router = APIRouter(
    prefix="/api/github",
    tags=["github"],
)

@router.get("/download-folder")
async def download_folder(
    owner: str = Query(..., description="GitHub repository owner/organization"),
    repo: str = Query(..., description="GitHub repository name"),
    folder_path: str = Query("", description="Folder path within the repository (e.g., 'src/components')"),
    token: Optional[str] = Query(None, description="GitHub personal access token for private repositories"),
    authorization: Optional[str] = Header(None, description="Authorization header with GitHub token (Bearer format)"),
    background: bool = Query(False, description="Process download in background")
):
    """
    Download a specific folder from a GitHub repository as a ZIP file.
    
    ## Authentication for Private Repositories:
    - Provide a GitHub personal access token with 'repo' scope using either:
      - The 'token' query parameter, or
      - The 'Authorization' header with format 'Bearer your-token'
    
    ## Notes:
    - If no folder path is specified, downloads the entire repository
    - For public repositories, a token is not required but recommended to avoid rate limits
    - For private repositories, a valid token with sufficient permissions is required
    - Set 'background=true' for large folders to process the download in the background
    """
    try:
        # Extract token from Authorization header if provided
        auth_token = None
        if authorization and authorization.startswith("Bearer "):
            auth_token = authorization.replace("Bearer ", "")
        
        # Use token from query parameter if authorization header not provided
        final_token = auth_token or token
        
        if background:
            # Start a background task and return a task ID
            task_id = await start_background_download(owner, repo, folder_path, final_token)
            return {
                "message": "Download started in background",
                "task_id": task_id,
                "status_url": f"/api/github/tasks/{task_id}",
                "download_url": f"/api/github/downloads/{task_id}"
            }
        else:
            # Process synchronously
            zip_buffer, filename = await download_folder_as_zip(owner, repo, folder_path, final_token)
            
            # Return the ZIP file as a downloadable response
            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/tasks/{task_id}", response_model=Dict)
async def check_task_status(
    task_id: str = Path(..., description="The ID of the background task")
):
    """Get the status of a background download task"""
    try:
        task_info = get_task_status(task_id)
        return task_info
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/downloads/{task_id}")
async def download_completed_task(
    task_id: str = Path(..., description="The ID of the background task")
):
    """Download the ZIP file from a completed background task"""
    try:
        file_path, filename = get_download_file(task_id)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/zip"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
