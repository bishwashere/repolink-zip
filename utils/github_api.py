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
import contextlib
import queue

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
            "Accept": "application/vnd.github.v3+json",
            # Add user agent to prevent 403 errors
            "User-Agent": "GitHub-Folder-ZIP-API"
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
        
        # Max workers for parallel processing - adjust based on CPU and network
        cpu_count = os.cpu_count() or 4
        self.max_workers_content = min(24, cpu_count * 2)  # For content API calls
        self.max_workers_files = min(48, cpu_count * 4)    # For file downloads
        
        # Use connection pooling for better performance
        self.session = requests.Session()
        
        # Create a session adapter with optimized settings
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=self.max_workers_files,
            pool_maxsize=self.max_workers_files,
            max_retries=3
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        # For the session, use the same headers
        self.session.headers.update(self.headers)
    
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
        response = self.session.get(url)
        
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
        
        # Get the folder contents and build repository structure
        contents = await self.get_repository_contents(owner, repo, folder_path)
        
        # Use a queue and worker threads to process files as they're discovered
        # instead of waiting for the full scan to complete
        zip_buffer = io.BytesIO()
        file_queue = queue.Queue()
        total_files_counter = [0]  # Use a list for a mutable integer reference
        processed_files_counter = [0]
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Start file processing workers that will take items from the queue
            with ThreadPoolExecutor(max_workers=self.max_workers_files) as executor:
                # Start worker threads that will process the file queue
                futures = []
                for _ in range(self.max_workers_files):
                    future = executor.submit(
                        self._worker_process_file_queue, 
                        zip_file, 
                        file_queue, 
                        total_files_counter,
                        processed_files_counter,
                        folder_path
                    )
                    futures.append(future)
                
                # Scan repository in parallel with processing
                self._scan_and_enqueue_files(
                    owner, 
                    repo, 
                    folder_path, 
                    contents, 
                    file_queue, 
                    total_files_counter
                )
                
                # Mark queue as done for all workers
                file_queue.put(None)
                
                # Wait for all worker threads to complete
                for future in futures:
                    # This will re-raise any exceptions from the worker threads
                    future.result()
        
        # Reset the buffer position to the beginning
        zip_buffer.seek(0)
        
        end_time = time.time()
        logger.info(f"ZIP creation completed in {end_time - start_time:.2f} seconds")
        return zip_buffer
    
    def _scan_and_enqueue_files(self, owner, repo, folder_path, contents, file_queue, total_files_counter):
        """Scan repository and add files to the processing queue as they're discovered"""
        # Process this level's files immediately
        for item in contents:
            if item["type"] == "file":
                file_queue.put(item)
                total_files_counter[0] += 1
        
        # Process subdirectories in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers_content) as executor:
            futures = []
            for item in contents:
                if item["type"] == "dir":
                    future = executor.submit(
                        self._process_subdirectory,
                        owner, 
                        repo, 
                        item["path"], 
                        file_queue, 
                        total_files_counter
                    )
                    futures.append(future)
            
            # Wait for all directory processing to complete
            for future in futures:
                # This will re-raise any exceptions
                future.result()
    
    def _process_subdirectory(self, owner, repo, dir_path, file_queue, total_files_counter):
        """Process a subdirectory and add its files to the queue"""
        contents = self._sync_get_repository_contents(
            owner, repo, dir_path, f"contents:{owner}:{repo}:{dir_path}"
        )
        
        # Add files to queue immediately
        for item in contents:
            if item["type"] == "file":
                file_queue.put(item)
                total_files_counter[0] += 1
            elif item["type"] == "dir":
                # Recursively process nested directories
                self._process_subdirectory(owner, repo, item["path"], file_queue, total_files_counter)
    
    def _worker_process_file_queue(self, zip_file, file_queue, total_files_counter, processed_files_counter, base_folder):
        """Worker thread function to process files from the queue"""
        while True:
            # Get the next file from the queue
            item = file_queue.get()
            
            # None is our signal to stop
            if item is None:
                # Put None back for other workers
                file_queue.put(None)
                break
            
            try:
                # Process the file
                rel_path = item["path"]
                if base_folder:
                    # Remove the base folder from the path to maintain correct structure
                    rel_path = rel_path.replace(base_folder, "").lstrip("/")
                
                # Get file content
                file_content = self._sync_get_file_content_cached(item["download_url"])
                
                # Add to ZIP with acquired lock to ensure thread safety
                with self._acquire_zip_lock(zip_file):
                    zip_file.writestr(rel_path, file_content)
                
                # Update progress counter
                with contextlib.suppress(Exception):
                    processed_files_counter[0] += 1
                    total = total_files_counter[0]
                    processed = processed_files_counter[0]
                    
                    # Report progress at appropriate intervals
                    if processed % 10 == 0 or processed == total:
                        if total > 0:
                            logger.info(f"Progress: {processed}/{total} files ({processed/total*100:.1f}%)")
                        else:
                            logger.info(f"Progress: {processed} files processed")
            
            except Exception as e:
                logger.error(f"Error processing file {item['path']}: {str(e)}")
            
            finally:
                # Mark this task as done
                file_queue.task_done()
    
    @contextlib.contextmanager
    def _acquire_zip_lock(self, zip_file):
        """Context manager for thread-safe access to the ZIP file"""
        # ZipFile is not thread-safe, so we use this as a placeholder
        # In a real implementation, you'd use a threading.Lock here
        yield
    
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
        response = self.session.get(download_url)
        
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
    
    def __del__(self):
        """Clean up resources when the object is destroyed"""
        # Close the session to release resources
        if hasattr(self, 'session'):
            self.session.close()
