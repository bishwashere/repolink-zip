import asyncio
import logging
import time
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# Configure logging
logger = logging.getLogger(__name__)

class CleanupManager:
    """Manages periodic cleanup tasks for the application"""
    
    def __init__(self, r2_storage=None):
        """Initialize the cleanup manager"""
        self.r2_storage = r2_storage
        self.cleanup_interval = int(os.getenv("CLEANUP_INTERVAL_HOURS", "12")) * 3600
        self.is_running = False
        self._cleanup_task = None
        
    async def start(self, r2_storage=None):
        """Start the cleanup task"""
        if r2_storage:
            self.r2_storage = r2_storage
            
        if self.is_running:
            logger.warning("Cleanup manager is already running")
            return
            
        if not self.r2_storage:
            logger.error("R2 storage not provided, cannot start cleanup manager")
            return
            
        self.is_running = True
        self._cleanup_task = asyncio.create_task(self._run_cleanup_loop())
        logger.info(f"Cleanup manager started, will run every {self.cleanup_interval//3600} hours")
    
    async def stop(self):
        """Stop the cleanup task"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("Cleanup manager stopped")
    
    async def _run_cleanup_loop(self):
        """Main cleanup loop that runs periodically"""
        try:
            while self.is_running:
                # Run immediately on startup
                await self._run_cleanup_tasks()
                
                # Wait for the next interval
                await asyncio.sleep(self.cleanup_interval)
        except asyncio.CancelledError:
            logger.info("Cleanup loop canceled")
            raise
        except Exception as e:
            logger.error(f"Error in cleanup loop: {str(e)}")
            if self.is_running:
                # If we're still supposed to be running, restart the loop
                asyncio.create_task(self._run_cleanup_loop())
    
    async def _run_cleanup_tasks(self):
        """Run all cleanup tasks"""
        try:
            # Log the start of cleanup
            logger.info("Starting scheduled cleanup tasks")
            start_time = time.time()
            
            # Run R2 file cleanup
            await self._cleanup_r2_files()
            
            # Log completion
            elapsed = time.time() - start_time
            logger.info(f"Cleanup tasks completed in {elapsed:.2f} seconds")
        except Exception as e:
            logger.error(f"Error running cleanup tasks: {str(e)}")
    
    async def _cleanup_r2_files(self):
        """Clean up expired files in R2 storage"""
        if not self.r2_storage:
            logger.warning("R2 storage not available, skipping file cleanup")
            return
            
        try:
            # Run the cleanup in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.r2_storage.cleanup_expired_files)
            
            deleted_count = result.get("deleted_count", 0)
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired files from R2 storage")
            else:
                logger.info("No expired files found in R2 storage")
                
            return result
        except Exception as e:
            logger.error(f"Error cleaning up R2 files: {str(e)}")
            return {"status": "error", "message": str(e)}

# Create a singleton instance
cleanup_manager = CleanupManager()
