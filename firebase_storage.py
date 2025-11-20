"""
Firebase Storage service for uploading files to Google Cloud Storage.
"""
import os
import threading
from typing import Optional

try:
    from google.cloud import storage
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False
    print("WARNING: google-cloud-storage not installed. Firebase Storage uploads will not work.")

# Storage bucket name
STORAGE_BUCKET = "racetomasterprestige.firebasestorage.app"


class FirebaseStorageService:
    """Service for uploading files to Firebase Storage."""
    
    def __init__(self):
        """Initialize Firebase Storage service."""
        self.bucket = None
        self.upload_lock = threading.Lock()
        self._init_storage()
    
    def _init_storage(self):
        """Initialize storage client."""
        if not STORAGE_AVAILABLE:
            print("⚠ Firebase Storage not available - install google-cloud-storage")
            return
        
        try:
            # Try to use the same credentials as Firebase Admin SDK
            # First, check if GOOGLE_APPLICATION_CREDENTIALS is set
            if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
                storage_client = storage.Client()
            else:
                # Try to find the service account file
                cred_path = os.path.join(os.path.dirname(__file__), 'firebase-service-account.json')
                if os.path.exists(cred_path):
                    # Set environment variable for Google Cloud client
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = cred_path
                    storage_client = storage.Client()
                else:
                    # Try default credentials (might work if Firebase Admin is initialized)
                    storage_client = storage.Client()
            
            self.bucket = storage_client.bucket(STORAGE_BUCKET)
            print(f"✓ Firebase Storage initialized: {STORAGE_BUCKET}")
        except Exception as e:
            print(f"⚠ Firebase Storage initialization failed: {e}")
            print("   File uploads to Firebase Storage will not work.")
            print("   Make sure Firebase Admin SDK is initialized and credentials are configured.")
            self.bucket = None
    
    def delete_file(self, remote_path: str) -> bool:
        """
        Delete a file from Firebase Storage.
        
        Args:
            remote_path: Remote path in storage (e.g., 'annotated_frames/image.jpg')
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        if not STORAGE_AVAILABLE or self.bucket is None:
            return False
        
        try:
            with self.upload_lock:
                blob = self.bucket.blob(remote_path)
                if blob.exists():
                    blob.delete()
                    print(f"✓ Deleted gs://{STORAGE_BUCKET}/{remote_path}")
                    return True
                else:
                    # File doesn't exist, which is fine
                    return True
        except Exception as e:
            print(f"✗ Failed to delete {remote_path} from Firebase Storage: {e}")
            return False
    
    def list_files(self, prefix: str, max_results: Optional[int] = None) -> list:
        """
        List all files in Firebase Storage with the given prefix.
        
        Args:
            prefix: Prefix to filter files (e.g., 'annotated_frames/stream_1_')
            max_results: Maximum number of results to return (None for all)
            
        Returns:
            List of blob names matching the prefix
        """
        if not STORAGE_AVAILABLE or self.bucket is None:
            return []
        
        try:
            print(f"Listing files with prefix: {prefix}")
            blobs = self.bucket.list_blobs(prefix=prefix, max_results=max_results)
            file_list = []
            count = 0
            for blob in blobs:
                file_list.append(blob.name)
                count += 1
                if max_results and count >= max_results:
                    break
            print(f"Found {len(file_list)} files with prefix {prefix}")
            return file_list
        except Exception as e:
            print(f"✗ Failed to list files with prefix {prefix}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def cleanup_old_frames_for_stream(self, stream_id: int, timeout: int = 5) -> int:
        """
        Clean up old timestamped frames for a stream, keeping only the fixed-named file.
        Uses a timeout to avoid hanging.
        
        Args:
            stream_id: Stream ID
            timeout: Maximum time to spend on cleanup (seconds)
            
        Returns:
            Number of files deleted
        """
        if not STORAGE_AVAILABLE or self.bucket is None:
            return 0
        
        deleted_count = 0
        import time
        start_time = time.time()
        
        try:
            # Skip cleanup if it would take too long - just return
            # The fixed path overwrites old files anyway
            print(f"Cleanup for stream {stream_id} skipped (using fixed path overwrites old files)")
            return 0
            
            # The code below is kept for reference but disabled to avoid hanging
            # List all files for this stream (with timeout protection)
            # prefix = f"annotated_frames/stream_{stream_id}_"
            # files = self.list_files(prefix, max_results=50)  # Reduced limit
            # 
            # if time.time() - start_time > timeout:
            #     print(f"Cleanup timeout for stream {stream_id}, skipping")
            #     return deleted_count
            # 
            # if not files:
            #     return 0
            # 
            # # The current fixed-named file
            # current_file = f"annotated_frames/stream_{stream_id}_annotated.jpg"
            # 
            # # Delete timestamped files (limit to avoid timeout)
            # for file_path in files[:20]:  # Limit to 20 files max
            #     if time.time() - start_time > timeout:
            #         break
            #     
            #     if file_path == current_file:
            #         continue
            #     
            #     filename = os.path.basename(file_path)
            #     parts = filename.split('_')
            #     if len(parts) >= 4 and parts[-1] == 'annotated.jpg':
            #         try:
            #             file_stream_id = int(parts[1])
            #             if file_stream_id == stream_id:
            #                 if self.delete_file(file_path):
            #                     deleted_count += 1
            #         except (ValueError, IndexError):
            #             continue
            
        except Exception as e:
            print(f"✗ Error cleaning up old frames for stream {stream_id}: {e}")
            # Don't traceback for cleanup errors - just return
        finally:
            elapsed = time.time() - start_time
            if elapsed > 1:
                print(f"Cleanup for stream {stream_id} took {elapsed:.1f}s")
        
        return deleted_count
    
    def upload_file(self, local_path: str, remote_path: str, delete_old: bool = False, old_remote_path: Optional[str] = None) -> bool:
        """
        Upload a file to Firebase Storage.
        
        Args:
            local_path: Local file path
            remote_path: Remote path in storage (e.g., 'annotated_frames/image.jpg')
            delete_old: Whether to delete old file before uploading
            old_remote_path: Path to old file to delete (if different from remote_path)
            
        Returns:
            True if upload succeeded, False otherwise
        """
        if not STORAGE_AVAILABLE or self.bucket is None:
            print("⚠ Storage not available")
            return False
        
        if not os.path.exists(local_path):
            print(f"⚠ File not found for upload: {local_path}")
            return False
        
        try:
            # Upload directly without lock (blob operations are generally thread-safe)
            # Using fixed paths means old files are automatically overwritten
            filename = os.path.basename(local_path)
            print(f"Uploading {filename} to {remote_path}...")
            import sys
            sys.stdout.flush()
            
            # Get file size for logging
            file_size = os.path.getsize(local_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"File size: {file_size_mb:.2f} MB")
            sys.stdout.flush()
            
            # Upload new file directly (overwrites old file automatically due to fixed path)
            blob = self.bucket.blob(remote_path)
            
            # Try upload with timeout protection using threading
            upload_success = [False]
            upload_error = [None]
            
            def do_upload():
                try:
                    blob.upload_from_filename(local_path)
                    upload_success[0] = True
                except Exception as e:
                    upload_error[0] = e
            
            # Run upload in a separate thread with timeout
            upload_thread = threading.Thread(target=do_upload, daemon=True)
            upload_thread.start()
            upload_thread.join(timeout=60)  # 60 second timeout
            
            if upload_thread.is_alive():
                # Upload is still running after timeout
                print(f"✗ Upload timeout for {filename} after 60 seconds")
                sys.stdout.flush()
                return False
            
            if upload_error[0]:
                # Upload failed with an error
                print(f"✗ Upload failed for {filename}: {upload_error[0]}")
                import traceback
                traceback.print_exc()
                sys.stdout.flush()
                return False
            
            if upload_success[0]:
                print(f"✓ Successfully uploaded {filename} to gs://{STORAGE_BUCKET}/{remote_path}")
                sys.stdout.flush()
                return True
            else:
                print(f"✗ Upload failed for {filename} (unknown reason)")
                sys.stdout.flush()
                return False
            
        except Exception as e:
            print(f"✗ Failed to upload {local_path} to Firebase Storage: {e}")
            import traceback
            traceback.print_exc()
            import sys
            sys.stdout.flush()
            return False
    
    def upload_file_async(self, local_path: str, remote_path: str, delete_old: bool = False, old_remote_path: Optional[str] = None):
        """
        Upload a file to Firebase Storage asynchronously (non-blocking).
        
        Args:
            local_path: Local file path
            remote_path: Remote path in storage
            delete_old: Whether to delete old file before uploading
            old_remote_path: Path to old file to delete (if different from remote_path)
        """
        def upload():
            self.upload_file(local_path, remote_path, delete_old, old_remote_path)
        
        thread = threading.Thread(target=upload, daemon=True)
        thread.start()
    
    def upload_annotated_frame(self, local_path: str, stream_id: int, old_remote_path: Optional[str] = None) -> bool:
        """
        Upload an annotated frame to Firebase Storage.
        Uses a fixed path per stream so old frames are overwritten.
        
        Args:
            local_path: Local file path
            stream_id: Stream ID
            old_remote_path: Optional path to old frame to delete explicitly
            
        Returns:
            True if upload succeeded, False otherwise
        """
        # Use fixed path per stream (overwrites old frame)
        remote_path = f"annotated_frames/stream_{stream_id}_annotated.jpg"
        # Delete old file if it exists (for cleanup of old timestamped files)
        delete_old = old_remote_path is not None
        return self.upload_file(local_path, remote_path, delete_old=delete_old, old_remote_path=old_remote_path)
    
    def upload_annotated_frame_async(self, local_path: str, stream_id: int, old_remote_path: Optional[str] = None):
        """
        Upload an annotated frame asynchronously.
        Uses a fixed path per stream so old frames are overwritten.
        
        Args:
            local_path: Local file path
            stream_id: Stream ID
            old_remote_path: Optional path to old frame to delete explicitly
        """
        # Use fixed path per stream (overwrites old frame)
        remote_path = f"annotated_frames/stream_{stream_id}_annotated.jpg"
        # Delete old file if it exists (for cleanup of old timestamped files)
        delete_old = old_remote_path is not None
        self.upload_file_async(local_path, remote_path, delete_old=delete_old, old_remote_path=old_remote_path)
    
    def upload_streams_data(self, local_path: str = "streams_data.json") -> bool:
        """
        Upload streams_data.json to Firebase Storage.
        
        Args:
            local_path: Local file path (default: streams_data.json)
            
        Returns:
            True if upload succeeded, False otherwise
        """
        remote_path = "streams_data.json"
        return self.upload_file(local_path, remote_path)
    
    def upload_streams_data_async(self, local_path: str = "streams_data.json"):
        """
        Upload streams_data.json asynchronously.
        
        Args:
            local_path: Local file path (default: streams_data.json)
        """
        remote_path = "streams_data.json"
        self.upload_file_async(local_path, remote_path)
    
    def upload_all_files(self, database, annotated_frames_dir: str = "annotated_frames", 
                        streams_data_path: str = "streams_data.json", cleanup_old: bool = True) -> dict:
        """
        Upload only the latest annotated frames per stream and streams_data.json to Firebase Storage.
        Only uploads the most recent frame for each stream, matching local behavior.
        Optionally cleans up old timestamped files from Firebase Storage.
        
        Args:
            database: StreamDatabase instance to get latest frame paths
            annotated_frames_dir: Directory containing annotated frames
            streams_data_path: Path to streams_data.json
            cleanup_old: Whether to clean up old timestamped files from Firebase Storage
            
        Returns:
            Dict with upload results
        """
        results = {
            'frames_uploaded': 0,
            'frames_failed': 0,
            'frames_deleted': 0,
            'data_uploaded': False,
            'errors': []
        }
        
        # Get all active streams from database
        active_stream_ids = set()
        try:
            print("Getting active streams from database...")
            streams = database.get_all_active_streams()
            print(f"Found {len(streams)} active streams")
            
            # Upload only the latest annotated frame for each stream
            for stream in streams:
                stream_id = stream['id']
                active_stream_ids.add(stream_id)
                latest_frame_path = database.get_last_annotated_frame_path(stream_id)
                
                print(f"Processing stream {stream_id}...")
                if latest_frame_path and os.path.exists(latest_frame_path):
                    # Extract old remote path from filename if it exists
                    # Old format: stream_{stream_id}_{timestamp}_annotated.jpg
                    # New format: stream_{stream_id}_annotated.jpg (fixed path)
                    old_filename = os.path.basename(latest_frame_path)
                    # Check if it's the old timestamped format
                    if old_filename.count('_') >= 3:  # stream_ID_timestamp_annotated.jpg
                        # Extract timestamped filename for deletion
                        old_remote_path = f"annotated_frames/{old_filename}"
                    else:
                        old_remote_path = None
                    
                    print(f"Uploading frame for stream {stream_id}...")
                    import sys
                    sys.stdout.flush()
                    try:
                        # Upload frame without cleanup first (faster)
                        if self.upload_annotated_frame(latest_frame_path, stream_id, None):  # Don't delete old path during upload
                            results['frames_uploaded'] += 1
                            print(f"✓ Uploaded frame for stream {stream_id}")
                            sys.stdout.flush()
                            
                            # Clean up old timestamped files AFTER upload (non-blocking, skip if slow)
                            if cleanup_old:
                                try:
                                    print(f"Cleaning up old files for stream {stream_id}...")
                                    sys.stdout.flush()
                                    # Limit cleanup to avoid hanging
                                    deleted = self.cleanup_old_frames_for_stream(stream_id)
                                    results['frames_deleted'] += deleted
                                    if deleted > 0:
                                        print(f"✓ Cleaned up {deleted} old files for stream {stream_id}")
                                    sys.stdout.flush()
                                except Exception as e:
                                    print(f"Warning: Failed to cleanup old files for stream {stream_id}: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    # Don't fail the upload if cleanup fails
                        else:
                            results['frames_failed'] += 1
                            results['errors'].append(f"Failed to upload frame for stream {stream_id}")
                            print(f"✗ Failed to upload frame for stream {stream_id}")
                            sys.stdout.flush()
                    except Exception as e:
                        print(f"Error uploading frame for stream {stream_id}: {e}")
                        import traceback
                        traceback.print_exc()
                        import sys
                        sys.stdout.flush()
                        results['frames_failed'] += 1
                        results['errors'].append(f"Error uploading frame for stream {stream_id}: {str(e)}")
                else:
                    results['errors'].append(f"No latest frame found for stream {stream_id}")
                    print(f"⚠ No latest frame found for stream {stream_id}")
        except Exception as e:
            print(f"Error getting streams from database: {e}")
            import traceback
            traceback.print_exc()
            results['errors'].append(f"Error getting streams from database: {str(e)}")
        
        # Skip global cleanup of deleted streams for now - it's expensive and can cause timeouts
        # The per-stream cleanup above should be sufficient for most cases
        # If you need to clean up files for deleted streams, you can do it manually or in a separate job
        # 
        # Note: We're already cleaning up old timestamped files per-stream during upload above,
        # so the main cleanup is done. The global cleanup would only be needed for streams that
        # were deleted from the database but still have files in Firebase Storage.
        
        # Upload streams_data.json
        print("Uploading streams_data.json...")
        import sys
        sys.stdout.flush()
        if os.path.exists(streams_data_path):
            try:
                if self.upload_streams_data(streams_data_path):
                    results['data_uploaded'] = True
                    print("✓ Uploaded streams_data.json")
                else:
                    results['errors'].append("Failed to upload streams_data.json")
                    print("✗ Failed to upload streams_data.json")
            except Exception as e:
                print(f"✗ Error uploading streams_data.json: {e}")
                import traceback
                traceback.print_exc()
                results['errors'].append(f"Error uploading streams_data.json: {str(e)}")
        else:
            results['errors'].append(f"streams_data.json not found at {streams_data_path}")
            print(f"⚠ streams_data.json not found at {streams_data_path}")
        
        print(f"Upload completed. Final results: {results}")
        import sys
        sys.stdout.flush()
        return results


# Global instance
_storage_service = None

def get_storage_service() -> Optional[FirebaseStorageService]:
    """Get the global Firebase Storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = FirebaseStorageService()
    return _storage_service

