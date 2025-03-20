from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.github_routes import router as github_router
import os
from dotenv import load_dotenv
import logging
import asyncio
from utils.cleanup_manager import cleanup_manager
from utils.r2_storage import R2Storage

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
    - Access private repositories using the API's built-in GitHub token
    - Simple URL-based API with query parameters
    - Store downloads in Cloudflare R2 for faster access
    - Automatic link expiration for security
    
    ## Authentication:
    The API uses a pre-configured GitHub token for accessing repositories.
    You don't need to provide your own token unless you want to access private repositories 
    that the default token doesn't have access to.
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

# Initialize storage and cleanup services
r2_storage = R2Storage()

# Start cleanup manager on application startup
@app.on_event("startup")
async def startup_event():
    # Only start the background task in non-serverless environments
    if not os.getenv("VERCEL", ""):
        await cleanup_manager.start(r2_storage)
        logger.info("Started background cleanup manager")

# Shutdown cleanup manager when application stops
@app.on_event("shutdown")
async def shutdown_event():
    # Only needed in non-serverless environments
    if not os.getenv("VERCEL", ""):
        await cleanup_manager.stop()
        logger.info("Stopped background cleanup manager")

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to GitHub Folder ZIP API. Use /docs for API documentation.",
        "features": [
            "Download folders from public GitHub repositories",
            "Access private repositories using the API's built-in GitHub token",
            "Customize folder path to download specific directories",
            "Store downloads in Cloudflare R2 for faster delivery",
            "Automatic file expiration for security"
        ],
        "documentation_url": "/docs"
    }

# Add an admin endpoint to manually trigger cleanup
@app.post("/api/admin/cleanup", include_in_schema=False)
async def trigger_cleanup():
    """
    Manually trigger the cleanup process
    This endpoint is hidden from the docs for security
    """
    # Run the cleanup in a background task
    cleanup_task = asyncio.create_task(cleanup_manager._run_cleanup_tasks())
    
    return {
        "message": "Cleanup process started",
        "status": "running"
    }

if __name__ == "__main__":
    import uvicorn
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=debug_mode)
