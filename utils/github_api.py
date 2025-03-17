import requests
import base64
import zipfile
import io
import os
import asyncio
import aiohttp
from typing import Dict, List, Optional, Set, Any
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        # Check cache first
        cache_key = f"contents:{owner}:{repo}:{path}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data

        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                await self._update_rate_limit(response)
                
                if response.status == 401:
                    raise Exception("Authentication failed. Please provide a valid GitHub token with sufficient permissions.")
                elif response.status == 403:
                    if self.rate_limit_remaining == 0:
                        reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.rate_limit_reset))
                        raise Exception(f"GitHub API rate limit exceeded. Resets at {reset_time}")
                    raise Exception("Insufficient permissions. Try using a GitHub token with 'repo' scope.")
                elif response.status == 404:
                    raise Exception(f"Repository or path not found. Check if the repository is private and you have access to it.")
                elif response.status != 200:
                    response_json = await response.json()
                    message = response_json.get('message', 'Unknown error')
                    raise Exception(f"Error fetching repository contents: {message}")
                
                data = await response.json()
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
            # Track processed files for progress reporting
            total_files = await self._count_files(owner, repo, folder_path, contents)
            processed_files = 0
            
            # Use asyncio.gather to parallelize file downloads
            await self._add_folder_to_zip(zip_file, owner, repo, folder_path, contents, folder_path, processed_files, total_files)
        
        # Reset the buffer position to the beginning
        zip_buffer.seek(0)
        
        end_time = time.time()
        logger.info(f"ZIP creation completed in {end_time - start_time:.2f} seconds")
        return zip_buffer
    
    async def _count_files(self, owner: str, repo: str, folder_path: str, contents: List[Dict]) -> int:
        """Count the total number of files in a folder structure"""
        count = 0
        tasks = []
        
        for item in contents:
            if item["type"] == "file":
                count += 1
            elif item["type"] == "dir":
                # Create task to get directory contents
                tasks.append(self.get_repository_contents(owner, repo, item["path"]))
        
        # Process subdirectories in parallel
        if tasks:
            results = await asyncio.gather(*tasks)
            for subdir_contents in results:
                for subdir_path, subdir_items in zip([item["path"] for item in contents if item["type"] == "dir"], results):
                    subcount = await self._count_files(owner, repo, subdir_path, subdir_items)
                    count += subcount
        
        return count
    
    async def _add_folder_to_zip(self, zip_file, owner, repo, folder_path, contents, base_folder, 
                                processed_files, total_files):
        """Recursively add files and folders to the ZIP file using async operations"""
        file_tasks = []
        dir_tasks = []
        
        # Prepare tasks for all files and directories
        for item in contents:
            # Get relative path for ZIP entry
            rel_path = item["path"]
            if base_folder:
                # Remove the base folder from the path to maintain correct structure
                rel_path = rel_path.replace(base_folder, "").lstrip("/")
            
            if item["type"] == "file":
                # Create a task for each file download
                file_tasks.append(self._process_file(zip_file, rel_path, item["download_url"]))
            
            elif item["type"] == "dir":
                # Create a task for each directory
                dir_tasks.append(self.get_repository_contents(owner, repo, item["path"]))
        
        # Process all file downloads in parallel
        if file_tasks:
            await asyncio.gather(*file_tasks)
            processed_files += len(file_tasks)
            if total_files > 0:
                logger.info(f"Progress: {processed_files}/{total_files} files ({processed_files/total_files*100:.1f}%)")
        
        # Process subdirectories in parallel
        if dir_tasks:
            subdir_contents = await asyncio.gather(*dir_tasks)
            subdir_tasks = []
            
            for i, subdir_items in enumerate(subdir_contents):
                # Find the directory item that corresponds to these contents
                dir_item = next((item for item in contents if item["type"] == "dir" and item["path"] == [item["path"] for item in contents if item["type"] == "dir"][i]), None)
                if dir_item:
                    # Process this subdirectory
                    subdir_tasks.append(
                        self._add_folder_to_zip(
                            zip_file, owner, repo, dir_item["path"], 
                            subdir_items, base_folder, processed_files, total_files
                        )
                    )
            
            if subdir_tasks:
                await asyncio.gather(*subdir_tasks)
    
    async def _process_file(self, zip_file, rel_path, download_url):
        """Process a single file: download and add to ZIP"""
        # Check cache first
        cache_key = f"file:{download_url}"
        file_content = self._get_from_cache(cache_key)
        
        if not file_content:
            file_content = await self._get_file_content(download_url)
            # Cache the file content
            self._add_to_cache(cache_key, file_content)
        
        # Add file to the ZIP (must synchronize access to the ZIP file)
        zip_file.writestr(rel_path, file_content)
    
    async def _get_file_content(self, download_url: str) -> bytes:
        """Download file content from GitHub asynchronously"""
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url, headers=self.headers) as response:
                await self._update_rate_limit(response)
                
                if response.status == 401:
                    raise Exception("Authentication failed. Please provide a valid GitHub token.")
                elif response.status == 403:
                    if self.rate_limit_remaining == 0:
                        reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.rate_limit_reset))
                        raise Exception(f"GitHub API rate limit exceeded. Resets at {reset_time}")
                    raise Exception("API rate limit exceeded or insufficient permissions.")
                elif response.status != 200:
                    raise Exception(f"Error downloading file: {response.status}")
                
                return await response.read()
    
    async def _update_rate_limit(self, response):
        """Update rate limit information from response headers"""
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
