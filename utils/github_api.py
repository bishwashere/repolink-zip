import requests
import base64
import zipfile
import io
import os
import time
import logging
import concurrent.futures
from typing import Dict, List, Optional, Set, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

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
        
        # Max workers for parallel processing
        self.max_workers = min(32, os.cpu_count() * 4)  # Use 4x CPU cores but cap at 32
    
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
            # Scan the repository structure first to build a complete list of files
            file_list = self._scan_repository_structure(owner, repo, folder_path, contents)
            logger.info(f"Found {len(file_list)} files to process")
            
            # Process files in parallel using thread pool
            self._process_files_parallel(zip_file, file_list, folder_path)
        
        # Reset the buffer position to the beginning
        zip_buffer.seek(0)
        
        end_time = time.time()
        logger.info(f"ZIP creation completed in {end_time - start_time:.2f} seconds")
        return zip_buffer
    
    def _scan_repository_structure(self, owner: str, repo: str, folder_path: str, contents: List[Dict]) -> List[Dict]:
        """Scan the repository structure to build a complete list of files"""
        file_list = []
        
        def scan_folder(path, items):
            for item in items:
                if item["type"] == "file":
                    file_list.append(item)
                elif item["type"] == "dir":
                    subdir_contents = self._sync_get_repository_contents(
                        owner, repo, item["path"], f"contents:{owner}:{repo}:{item['path']}"
                    )
                    scan_folder(item["path"], subdir_contents)
        
        scan_folder(folder_path, contents)
        return file_list
    
    def _process_files_parallel(self, zip_file, file_list, base_folder):
        """Process files in parallel using a thread pool"""
        total_files = len(file_list)
        processed_files = 0
        
        def process_file(file_item):
            nonlocal processed_files
            rel_path = file_item["path"]
            if base_folder:
                # Remove the base folder from the path to maintain correct structure
                rel_path = rel_path.replace(base_folder, "").lstrip("/")
            
            # Get file content
            file_content = self._sync_get_file_content_cached(file_item["download_url"])
            
            # Store file data to return to the calling function
            return (rel_path, file_content)
        
        # Use a thread pool to process files in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {executor.submit(process_file, file_item): file_item for file_item in file_list}
            
            # As each future completes, add its file to the ZIP
            for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
                try:
                    rel_path, file_content = future.result()
                    zip_file.writestr(rel_path, file_content)
                    
                    # Update progress
                    processed_files += 1
                    if processed_files % 10 == 0 or processed_files == total_files:
                        logger.info(f"Progress: {processed_files}/{total_files} files ({processed_files/total_files*100:.1f}%)")
                except Exception as e:
                    file_item = future_to_file[future]
                    logger.error(f"Error processing file {file_item['path']}: {str(e)}")
    
    def _sync_get_file_content_cached(self, download_url: str) -> bytes:
        """Get file content with caching"""
        # Check cache first
        cache_key = f"file:{download_url}"
        file_content = self._get_from_cache(cache_key)
        
        if not file_content:
            file_content = self._sync_get_file_content(download_url)
            # Cache the file content
            self._add_to_cache(cache_key, file_content)
        
        return file_content
    
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
