from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.github_routes import router as github_router
import os
from dotenv import load_dotenv
import logging

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

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to GitHub Folder ZIP API. Use /docs for API documentation.",
        "features": [
            "Download folders from public GitHub repositories",
            "Access private repositories using the API's built-in GitHub token",
            "Customize folder path to download specific directories",
            "Store downloads in Cloudflare R2 for faster delivery"
        ],
        "documentation_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=debug_mode)
