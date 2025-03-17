from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.github_routes import router as github_router
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="GitHub Folder ZIP API",
    description="""
    API to download specific folders from GitHub repositories as ZIP files.
    
    ## Features:
    - Download any folder from public GitHub repositories
    - Access private repositories with a valid GitHub token
    - Simple URL-based API with query parameters
    
    ## Private Repository Access:
    To access private repositories, you need a GitHub Personal Access Token with 'repo' scope.
    Provide it using one of these methods:
    1. Add a 'token' query parameter: `/api/github/download-folder?owner=user&repo=myrepo&token=your-token`
    2. Send an Authorization header: `Authorization: Bearer your-token`
    """,
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(github_router)

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to GitHub Folder ZIP API. Use /docs for API documentation.",
        "features": [
            "Download folders from public GitHub repositories",
            "Access private repositories with a GitHub token",
            "Customize folder path to download specific directories"
        ],
        "documentation_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=debug_mode)
