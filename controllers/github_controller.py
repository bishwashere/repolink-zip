from fastapi import HTTPException
from utils.github_api import GitHubAPI
from utils.r2_storage import R2Storage
import io
from typing import Optional, Dict, Tuple, Union
import time
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize R2 storage
r2_storage = R2Storage()

async def download_folder_as_zip(
    owner: str, 
    repo: str, 
    folder_path: str, 
    token: Optional[str] = None
) -> Tuple[Union[Dict, io.BytesIO], str]:
    """
    Controller function to handle downloading a folder as a ZIP file and uploading to R2
    
    Returns:
        Tuple containing either:
        - (Dict with file info including download_url, filename string) if R2 upload succeeds
        - (BytesIO containing the ZIP data, filename string) if R2 upload fails
    """
    try:
        # Initialize GitHub API with optional token
        github_api = GitHubAPI(token)
        
        # Create ZIP file from the specified folder
        zip_buffer = await github_api.create_zip_from_folder(owner, repo, folder_path)
        
        # Create a meaningful filename for the download
        folder_name = folder_path.strip('/').split('/')[-1] if folder_path.strip('/') else repo
        timestamp = int(time.time())
        filename = f"{owner}_{repo}_{folder_name}_{timestamp}.zip"
        
        # Upload the ZIP file to R2 storage
        r2_key = f"github-zips/{owner}/{repo}/{filename}"
        
        # Upload to R2 and get the URL
        zip_url = r2_storage.upload_file(zip_buffer, r2_key)
        
        if not zip_url:
            # Fallback to direct response if R2 upload fails
            logger.warning("R2 upload failed, returning direct file response")
            return zip_buffer, filename
        
        # Get file size for response
        file_size = zip_buffer.getbuffer().nbytes
        
        # Return the file URL and information
        return {
            "success": True,
            "message": "ZIP file created and uploaded successfully",
            "data": {
                "filename": filename,
                "download_url": zip_url,
                "size_bytes": file_size,
                "size_formatted": format_size(file_size),
                "expires_in_days": r2_storage.expiration_days,
                "source": {
                    "owner": owner,
                    "repo": repo,
                    "folder_path": folder_path
                }
            }
        }, filename
        
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

def format_size(size_bytes):
    """Format bytes to human-readable size"""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
