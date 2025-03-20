import boto3
import os
import io
import logging
import time
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from typing import Optional, Tuple, List, Dict

# Configure logging
logger = logging.getLogger(__name__)

class R2Storage:
    def __init__(self):
        """Initialize Cloudflare R2 storage client"""
        self.bucket_name = os.getenv("R2_BUCKET_NAME")
        self.access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.endpoint_url = os.getenv("R2_ENDPOINT_URL")
        self.region = os.getenv("R2_REGION", "auto")
        self.public_url = os.getenv("R2_PUBLIC_URL")
        self.expiration_days = int(os.getenv("R2_EXPIRATION_DAYS", "7"))
        
        # Link expiration settings
        self.link_expiration_hours = int(os.getenv("DOWNLOAD_LINK_EXPIRATION_HOURS", "24"))
        self.cleanup_days = int(os.getenv("R2_CLEANUP_DAYS", "30"))
        
        # Check if required configuration is available
        if not all([self.bucket_name, self.access_key, self.secret_key, self.endpoint_url]):
            logger.warning("R2 storage configuration incomplete. Some features may not work.")
        
        self._client = None
        self._resource = None
    
    @property
    def client(self):
        """Lazy initialization of S3/R2 client"""
        if not self._client and all([self.access_key, self.secret_key, self.endpoint_url]):
            self._client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region
            )
        return self._client
    
    @property
    def resource(self):
        """Lazy initialization of S3/R2 resource"""
        if not self._resource and all([self.access_key, self.secret_key, self.endpoint_url]):
            self._resource = boto3.resource(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region
            )
        return self._resource
    
    def upload_file(self, file_data: io.BytesIO, key: str, content_type: str = "application/zip") -> Optional[str]:
        """
        Upload a file to R2 storage
        
        Args:
            file_data: The file data as BytesIO
            key: The storage key/path for the file
            content_type: The MIME type of the file
            
        Returns:
            The URL of the uploaded file or None if upload failed
        """
        if not self.client:
            logger.error("R2 client not initialized. Check your configuration.")
            return None
        
        try:
            # Set expiration date for the object
            expiration_date = datetime.now() + timedelta(days=self.expiration_days)
            
            # Add metadata for tracking and expiration
            metadata = {
                'created_at': datetime.now().isoformat(),
                'expires_at': expiration_date.isoformat(),
            }
            
            # Upload the file
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_data,
                ContentType=content_type,
                Expires=expiration_date,
                Metadata=metadata
            )
            
            # Return the URL with a shorter expiration time for the actual link
            if self.public_url:
                return f"{self.public_url.rstrip('/')}/{key}"
            else:
                # Generate a presigned URL that expires sooner than the file itself
                return self.generate_presigned_url(key)
                
        except ClientError as e:
            logger.error(f"Error uploading file to R2: {str(e)}")
            return None
    
    def generate_presigned_url(self, key: str, expiration: int = None) -> Optional[str]:
        """
        Generate a presigned URL for accessing a private object
        
        Args:
            key: The storage key/path of the object
            expiration: URL expiration time in seconds (default: based on settings)
            
        Returns:
            A presigned URL for the object or None if generation failed
        """
        if not self.client:
            logger.error("R2 client not initialized. Check your configuration.")
            return None
        
        if expiration is None:
            # Use the configured link expiration time (in hours) converted to seconds
            expiration = self.link_expiration_hours * 3600
            
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {str(e)}")
            return None
    
    def delete_file(self, key: str) -> bool:
        """
        Delete a file from R2 storage
        
        Args:
            key: The storage key/path of the object to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        if not self.client:
            logger.error("R2 client not initialized. Check your configuration.")
            return False
            
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"Deleted file from R2: {key}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting file from R2: {str(e)}")
            return False
    
    def list_expired_files(self, prefix: str = "github-zips/") -> List[str]:
        """
        List files that are older than the cleanup age and should be deleted
        
        Args:
            prefix: Only list objects with this prefix
            
        Returns:
            List of object keys that are expired
        """
        if not self.client:
            logger.warning("R2 client not initialized, cannot check for expired files")
            return []
            
        try:
            # Calculate cutoff date for expiration
            cutoff_date = datetime.now() - timedelta(days=self.cleanup_days)
            expired_keys = []
            
            # List objects in the bucket with the given prefix
            paginator = self.client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' not in page:
                    continue
                    
                for obj in page['Contents']:
                    # Check if the object is older than our cutoff
                    if obj['LastModified'].replace(tzinfo=None) < cutoff_date:
                        expired_keys.append(obj['Key'])
            
            return expired_keys
            
        except ClientError as e:
            logger.error(f"Error listing expired files: {str(e)}")
            return []
    
    def cleanup_expired_files(self) -> Dict:
        """
        Delete files that are older than the cleanup age
        
        Returns:
            A dictionary with the cleanup results
        """
        if not self.client:
            logger.warning("R2 client not initialized, cannot clean up expired files")
            return {"status": "error", "message": "R2 client not initialized"}
            
        try:
            # Get list of expired files
            expired_keys = self.list_expired_files()
            
            if not expired_keys:
                logger.info("No expired files to clean up")
                return {
                    "status": "success", 
                    "message": "No expired files found",
                    "deleted_count": 0
                }
            
            # Delete files in batches of 1000 (S3 limit for delete_objects)
            batch_size = 1000
            deleted_count = 0
            
            for i in range(0, len(expired_keys), batch_size):
                batch = expired_keys[i:i+batch_size]
                delete_dict = {
                    'Objects': [{'Key': key} for key in batch],
                    'Quiet': True
                }
                
                self.client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete=delete_dict
                )
                
                deleted_count += len(batch)
                logger.info(f"Deleted {len(batch)} expired files (batch {i//batch_size + 1})")
            
            logger.info(f"Cleanup completed: deleted {deleted_count} expired files")
            return {
                "status": "success",
                "message": f"Cleanup completed successfully",
                "deleted_count": deleted_count,
                "deleted_files": expired_keys
            }
            
        except ClientError as e:
            error_message = f"Error cleaning up expired files: {str(e)}"
            logger.error(error_message)
            return {"status": "error", "message": error_message}
    
    def check_file_exists(self, key: str) -> bool:
        """
        Check if a file exists in R2 storage
        
        Args:
            key: The storage key/path of the object
            
        Returns:
            True if file exists, False otherwise
        """
        if not self.client:
            return False
            
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False
