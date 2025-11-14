"""
Module for capturing frames from Twitch streams.
"""
import cv2
import subprocess
import threading
import queue
import time
import os
import shutil
import numpy as np
from typing import Optional, Generator


class StreamCapture:
    """Captures frames from a Twitch stream URL."""
    
    def __init__(self, stream_url: str):
        """
        Initialize stream capture.
        
        Args:
            stream_url: Twitch stream URL or username
        """
        self.stream_url = stream_url
        self.process: Optional[subprocess.Popen] = None
        self.frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
    def _normalize_url(self, url: str) -> str:
        """Convert username or URL to proper Twitch URL."""
        url = url.strip()
        if not url.startswith('http'):
            url = f'https://www.twitch.tv/{url}'
        return url
    
    def _find_streamlink(self) -> Optional[str]:
        """Find streamlink executable."""
        # First try shutil.which which uses PATH
        streamlink_path = shutil.which('streamlink')
        if streamlink_path:
            return streamlink_path
        
        # Fallback to known locations
        possible_paths = [
            '/home/noah/raceToPrestigeTracker/venv/bin/streamlink',
            '/usr/local/bin/streamlink',
            '/usr/bin/streamlink',
        ]
        
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        
        return None
    
    def _capture_frames(self):
        """Internal method to capture frames in a separate thread."""
        url = self._normalize_url(self.stream_url)
        cap = None
        
        try:
            # Find streamlink
            streamlink_path = self._find_streamlink()
            if not streamlink_path:
                raise Exception("streamlink not found. Please install streamlink: pip install streamlink")
            
            # Get the stream URL from streamlink with retry logic
            # Use longer timeout (25 seconds) to match live check timeout
            max_retries = 3
            retry_delay = 2  # seconds between retries
            stream_url = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    print(f"Getting stream URL (attempt {attempt}/{max_retries})...")
                    cmd_get_url = [streamlink_path, '--stream-url', url, 'best']
                    result = subprocess.run(
                        cmd_get_url,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=25  # Increased timeout to 25 seconds
                    )
                    
                    if result.returncode == 0:
                        stream_url = result.stdout.strip()
                        if stream_url:
                            print(f"✓ Stream URL obtained (attempt {attempt})")
                            break
                        else:
                            print(f"✗ Empty stream URL on attempt {attempt}")
                    else:
                        error_msg = result.stderr[:200] if result.stderr else "Unknown error"
                        print(f"✗ Failed to get stream URL on attempt {attempt}: {error_msg}")
                        
                        # Don't retry if stream is clearly not available
                        if 'No playable streams found' in error_msg or 'No streams found' in error_msg:
                            print(f"Stream is not available (not live or ended)")
                            return
                        
                except subprocess.TimeoutExpired:
                    print(f"✗ Timeout getting stream URL (attempt {attempt}/{max_retries})")
                    if attempt < max_retries:
                        print(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                    else:
                        print("All attempts failed - timeout getting stream URL")
                        return
                except Exception as e:
                    print(f"✗ Error getting stream URL (attempt {attempt}): {e}")
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                    else:
                        raise
            
            if not stream_url:
                print("Failed to get stream URL after all retries")
                return
            
            # Use OpenCV to read directly from the stream URL
            print(f"Opening video capture for stream...")
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                raise Exception("Failed to open video capture")
            
            print(f"✓ Video capture opened successfully")
            
            # Minimize buffer to reduce latency
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Optionally resize frames to reduce memory usage (configurable via FRAME_SCALE env var)
            # Default to 1.0 (no scaling), 0.5 = half size (~4x less memory), 0.75 = 75% size
            frame_scale = float(os.environ.get('FRAME_SCALE', '1.0'))
            
            frame_count = 0
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    # Stream might have ended or connection lost
                    print("Failed to read frame, stream may have ended")
                    break
                
                frame_count += 1
                if frame_count == 1:
                    print(f"✓ Successfully captured first frame from stream")
                
                # Optionally resize frame to reduce memory usage
                if frame is not None and frame_scale < 1.0:
                    height, width = frame.shape[:2]
                    new_width = int(width * frame_scale)
                    new_height = int(height * frame_scale)
                    frame = cv2.resize(frame, (new_width, new_height))
                
                # Keep only the latest frame to minimize memory usage
                if not self.frame_queue.full():
                    self.frame_queue.put(frame)
                else:
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put(frame)
                    except queue.Empty:
                        pass
                        
        except subprocess.TimeoutExpired:
            print(f"Timeout getting stream URL for {url}")
        except Exception as e:
            print(f"Error capturing stream ({url}): {e}")
            import traceback
            traceback.print_exc()
        finally:
            if cap is not None:
                cap.release()
                print(f"Video capture released for {url}")
            if self.process:
                self.process.terminate()
                self.process.wait()
    
    def start(self):
        """Start capturing frames from the stream."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_frames, daemon=True)
        self.thread.start()
        # Don't sleep here - let it initialize in background
    
    def stop(self):
        """Stop capturing frames."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        if self.process:
            self.process.terminate()
            self.process.wait()
    
    def get_frame(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Get the latest frame from the stream.
        
        Args:
            timeout: Maximum time to wait for a frame
            
        Returns:
            Latest frame as numpy array, or None if unavailable
        """
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def is_active(self) -> bool:
        """Check if stream capture is active."""
        return self.running and self.thread and self.thread.is_alive()

