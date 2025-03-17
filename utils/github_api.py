import requests
import base64
import zipfile
import io
import os
import time
import logging
from typing import Dict, List, Optional, Set, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set global flag for async availability
ASYNC_AVAILABLE = False
logger.info("Using synchronous methods for GitHub API interactions")

class GitHubAPI:
    def __init__(self, token: Optional[str] = None):
        """Initialize GitHub API with optional token for authentication"""
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Use provided token, fallback to environment variable if not provided
        final_token = token or os.getenv("GITHUB_TOKEN")
        if final_token:
            # Use Bearer token format which is recommended by GitHub
            self.headers["Authorization"] = f"Bearer {final_token}"
        
        # Set up in-memory cache
        self._cache = {}
        self._cache_ttl = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minutes default
        
        # Track rate limits
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = 0
    
    async def get_repository_contents(self, owner: str, repo: str, path: str = "") -> List[Dict]:
        """Fetch contents of a repository at a specific path"""
        # For compatibility with async code, we keep the async signature but use synchronous implementation
        return self._sync_get_repository_contents(owner, repo, path, f"contents:{owner}:{repo}:{path}")
    
    def _sync_get_repository_contents(self, owner: str, repo: str, path: str, cache_key: str) -> List[Dict]:
        """Synchronous implementation of repository contents retrieval"""
        # Check cache first
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=self.headers)
        
        self._sync_update_rate_limit(response)
        
        if response.status_code == 401:
            raise Exception("Authentication failed. Please provide a valid GitHub token with sufficient permissions.")
        elif response.status_code == 403:
            if self.rate_limit_remaining == 0:
                reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.rate_limit_reset))
                raise Exception(f"GitHub API rate limit exceeded. Resets at {reset_time}")
            raise Exception("Insufficient permissions. Try using a GitHub token with 'repo' scope.")
        elif response.status_code == 404:
            raise Exception(f"Repository or path not found. Check if the repository is private and you have access to it.")
        elif response.status_code != 200:
            message = response.json().get('message', 'Unknown error')
            raise Exception(f"Error fetching repository contents: {message}")
        
        data = response.json()
        # Store in cache
        self._add_to_cache(cache_key, data)
        return data

    async def create_zip_from_folder(self, owner: str, repo: str, folder_path: str) -> io.BytesIO:
        """Create a ZIP file from a folder in a GitHub repository"""
        start_time = time.time()
        logger.info(f"Starting ZIP creation for {owner}/{repo}/{folder_path}")
        
        # Get the folder contents
        contents = await self.get_repository_contents(owner, repo, folder_path)
        
        # Create a ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Use synchronous methods
            total_files = self._sync_count_files(owner, repo, folder_path, contents)
            processed_files = 0
            self._sync_add_folder_to_zip(zip_file, owner, repo, folder_path, contents, folder_path, processed_files, total_files)
        
        # Reset the buffer position to the beginning
        zip_buffer.seek(0)
        
        end_time = time.time()
        logger.info(f"ZIP creation completed in {end_time - start_time:.2f} seconds")
        return zip_buffer
    
    def _sync_count_files(self, owner: str, repo: str, folder_path: str, contents: List[Dict]) -> int:
        """Count the total number of files in a folder structure (synchronous version)"""
        count = 0
        
        for item in contents:
            if item["type"] == "file":
                count += 1
            elif item["type"] == "dir":
                subdir_contents = self._sync_get_repository_contents(owner, repo, item["path"], f"contents:{owner}:{repo}:{item['path']}")
                count += self._sync_count_files(owner, repo, item["path"], subdir_contents)
        
        return count
    
    def _sync_add_folder_to_zip(self, zip_file, owner, repo, folder_path, contents, base_folder, 
                              processed_files, total_files):
        """Recursively add files and folders to the ZIP file (synchronous version)"""
        for item in contents:
            # Get relative path for ZIP entry
            rel_path = item["path"]
            if base_folder:
                # Remove the base folder from the path to maintain correct structure
                rel_path = rel_path.replace(base_folder, "").lstrip("/")
            
            if item["type"] == "file":
                # Process file
                self._sync_process_file(zip_file, rel_path, item["download_url"])
                processed_files += 1
                if total_files > 0 and processed_files % 10 == 0:
                    logger.info(f"Progress: {processed_files}/{total_files} files ({processed_files/total_files*100:.1f}%)")
            
            elif item["type"] == "dir":
                # Process directory
                subdir_contents = self._sync_get_repository_contents(owner, repo, item["path"], f"contents:{owner}:{repo}:{item['path']}")
                self._sync_add_folder_to_zip(zip_file, owner, repo, item["path"], subdir_contents, base_folder, processed_files, total_files)
    
    def _sync_process_file(self, zip_file, rel_path, download_url):
        """Process a single file: download and add to ZIP (synchronous version)"""
        # Check cache first
        cache_key = f"file:{download_url}"
        file_content = self._get_from_cache(cache_key)
        
        if not file_content:
            file_content = self._sync_get_file_content(download_url)
            # Cache the file content
            self._add_to_cache(cache_key, file_content)
        
        # Add file to the ZIP
        zip_file.writestr(rel_path, file_content)
    
    def _sync_get_file_content(self, download_url: str) -> bytes:
        """Download file content from GitHub (synchronous version)"""
        response = requests.get(download_url, headers=self.headers)
        
        self._sync_update_rate_limit(response)
        
        if response.status_code == 401:
            raise Exception("Authentication failed. Please provide a valid GitHub token.")
        elif response.status_code == 403:
            if self.rate_limit_remaining == 0:
                reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.rate_limit_reset))
                raise Exception(f"GitHub API rate limit exceeded. Resets at {reset_time}")
            raise Exception("API rate limit exceeded or insufficient permissions.")
        elif response.status_code != 200:
            raise Exception(f"Error downloading file: {response.status_code}")
        
        return response.content
    
    def _sync_update_rate_limit(self, response):
        """Update rate limit information from response headers (synchronous version)"""
        try:
            self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', self.rate_limit_remaining))
            self.rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', self.rate_limit_reset))
        except (ValueError, TypeError):
            pass  # Keep existing values if headers are missing or invalid
    
    def _add_to_cache(self, key: str, data: Any):
        """Add data to the in-memory cache with timestamp"""
        self._cache[key] = {
            'timestamp': time.time(),
            'data': data
        }
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get data from cache if it exists and is not expired"""
        if key in self._cache:
            cache_item = self._cache[key]
            if time.time() - cache_item['timestamp'] < self._cache_ttl:
                return cache_item['data']
            else:
                # Remove expired item
                del self._cache[key]
        return None
