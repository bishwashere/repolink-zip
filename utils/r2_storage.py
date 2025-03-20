import boto3
import os
import io
import logging
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from typing import Optional, Tuple

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
            
            # Upload the file
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_data,
                ContentType=content_type,
                Expires=expiration_date
            )
            
            # Return the URL 
            if self.public_url:
                return f"{self.public_url.rstrip('/')}/{key}"
            else:
                # Generate a presigned URL if no public URL is configured
                return self.generate_presigned_url(key)
                
        except ClientError as e:
            logger.error(f"Error uploading file to R2: {str(e)}")
            return None
    
    def generate_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        """
        Generate a presigned URL for accessing a private object
        
        Args:
            key: The storage key/path of the object
            expiration: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            A presigned URL for the object or None if generation failed
        """
        if not self.client:
            logger.error("R2 client not initialized. Check your configuration.")
            return None
            
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
            return True
        except ClientError as e:
            logger.error(f"Error deleting file from R2: {str(e)}")
            return False
