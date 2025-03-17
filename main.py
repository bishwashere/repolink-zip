from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.github_routes import router as github_router
import os
from dotenv import load_dotenv
import asyncio
import logging
from controllers.github_controller import cleanup_old_tasks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file if it exists
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.info("Loaded environment variables from .env file")
else:
    logger.info("No .env file found, using environment variables")

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

# Start the background task cleanup process on startup
@app.on_event("startup")
async def startup_event():
    # Start the cleanup task if not running on Vercel
    if not os.environ.get("VERCEL"):
        asyncio.create_task(cleanup_old_tasks())
        logger.info("Started background task cleanup process")
    else:
        logger.info("Running on Vercel, skipping background cleanup task")

if __name__ == "__main__":
    import uvicorn
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=debug_mode)
