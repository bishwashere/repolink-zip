from fastapi import HTTPException
from utils.github_api import GitHubAPI
from utils.r2_storage import R2Storage
import io
from typing import Optional, Dict, Tuple, Union
import time
import os
import logging
import hashlib
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize R2 storage
r2_storage = R2Storage()

# Cache of recent downloads to avoid regenerating the same ZIP file 
# if requested multiple times in quick succession
_download_cache = {}
_cache_ttl = int(os.getenv("ZIP_CACHE_TTL_SECONDS", "300"))  # Default 5 minutes for ZIP file cache

# Get link expiration time from environment
link_expiration_hours = int(os.getenv("DOWNLOAD_LINK_EXPIRATION_HOURS", "24"))

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
        # Create a cache key for this specific request
        folder_path_normalized = folder_path.strip('/')
        cache_key = f"{owner}:{repo}:{folder_path_normalized}:{token or 'default'}"
        cache_hash = hashlib.md5(cache_key.encode()).hexdigest()
        
        # Check if we have a recent cached result
        current_time = time.time()
        if cache_hash in _download_cache:
            cache_entry = _download_cache[cache_hash]
            if current_time - cache_entry['timestamp'] < _cache_ttl:
                logger.info(f"Using cached result for {owner}/{repo}/{folder_path_normalized}")
                
                # Check if the cached URL has expired
                if isinstance(cache_entry['result'], dict) and 'data' in cache_entry['result']:
                    data = cache_entry['result']['data']
                    if 'expires_at' in data and data['expires_at']:
                        expires_at = datetime.fromisoformat(data['expires_at'])
                        
                        # If link is expired, regenerate it
                        if datetime.now() > expires_at:
                            if r2_storage.check_file_exists(data.get('r2_key')):
                                # Regenerate presigned URL if file still exists
                                new_url = r2_storage.generate_presigned_url(data.get('r2_key'))
                                if new_url:
                                    # Update expiration
                                    new_expires = datetime.now() + timedelta(hours=link_expiration_hours)
                                    data['download_url'] = new_url
                                    data['expires_at'] = new_expires.isoformat()
                                    logger.info(f"Regenerated expired link for {data.get('r2_key')}")
                
                return cache_entry['result'], cache_entry['filename']
            else:
                # Remove expired entry
                del _download_cache[cache_hash]
        
        # Initialize GitHub API with optional token
        github_api = GitHubAPI(token)
        
        # Create ZIP file from the specified folder
        zip_buffer = await github_api.create_zip_from_folder(owner, repo, folder_path)
        
        # Create a meaningful filename for the download
        folder_name = folder_path_normalized.split('/')[-1] if folder_path_normalized else repo
        timestamp = int(time.time())
        filename = f"{owner}_{repo}_{folder_name}_{timestamp}.zip"
        
        # Upload the ZIP file to R2 storage
        r2_key = f"github-zips/{owner}/{repo}/{filename}"
        
        # Upload to R2 and get the URL
        zip_url = r2_storage.upload_file(zip_buffer, r2_key)
        
        # Calculate expiration time
        expires_at = datetime.now() + timedelta(hours=link_expiration_hours)
        
        # Create the response
        if not zip_url:
            # Fallback to direct response if R2 upload fails
            logger.warning("R2 upload failed, returning direct file response")
            result = zip_buffer, filename
        else:
            # Get file size for response
            file_size = zip_buffer.getbuffer().nbytes
            
            # Create result dictionary
            result = {
                "success": True,
                "message": "ZIP file created and uploaded successfully",
                "data": {
                    "filename": filename,
                    "download_url": zip_url,
                    "size_bytes": file_size,
                    "size_formatted": format_size(file_size),
                    "expires_in_days": r2_storage.expiration_days,
                    "expires_at": expires_at.isoformat(),
                    "r2_key": r2_key,  # Store for link regeneration
                    "source": {
                        "owner": owner,
                        "repo": repo,
                        "folder_path": folder_path
                    }
                }
            }, filename
        
        # Cache the result
        _download_cache[cache_hash] = {
            'timestamp': current_time,
            'result': result[0],  # The response data or buffer
            'filename': result[1]  # The filename
        }
        
        return result
        
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
