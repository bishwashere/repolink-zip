from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from controllers.github_controller import download_folder_as_zip
from typing import Optional
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
    token: Optional[str] = Query(None, description="Optional: Override the default GitHub token for this request")
):
    """
    Download a specific folder from a GitHub repository as a ZIP file.
    
    ## Notes:
    - If no folder path is specified, downloads the entire repository
    - The API uses a default GitHub token for authentication
    - You can optionally provide your own token to override the default one
    - Returns a download URL where the ZIP file can be accessed
    """
    try:
        # Process the download and get result
        result, filename = await download_folder_as_zip(owner, repo, folder_path, token)
        
        # If result is a dictionary with download_url, return JSON response
        if isinstance(result, dict):
            return JSONResponse(content=result)
        else:
            # Fallback to direct file download if R2 storage failed
            return StreamingResponse(
                result,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
