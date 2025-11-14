"""
Module for capturing frames from Twitch streams.
"""
import cv2
import subprocess
import threading
import queue
import time
import os
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
    
    def _capture_frames(self):
        """Internal method to capture frames in a separate thread."""
        url = self._normalize_url(self.stream_url)
        cap = None
        
        try:
            # Get the stream URL from streamlink
            cmd_get_url = ['streamlink', '--stream-url', url, 'best']
            result = subprocess.run(
                cmd_get_url,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                raise Exception(f"Failed to get stream URL: {result.stderr}")
            
            stream_url = result.stdout.strip()
            print(f"Stream URL obtained, starting capture...")
            
            # Use OpenCV to read directly from the stream URL
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                raise Exception("Failed to open video capture")
            
            # Minimize buffer to reduce latency
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Optionally resize frames to reduce memory usage (configurable via FRAME_SCALE env var)
            # Default to 1.0 (no scaling), 0.5 = half size (~4x less memory), 0.75 = 75% size
            frame_scale = float(os.environ.get('FRAME_SCALE', '1.0'))
            
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    # Stream might have ended or connection lost
                    print("Failed to read frame, stream may have ended")
                    break
                
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
            print("Timeout getting stream URL")
        except Exception as e:
            print(f"Error capturing stream: {e}")
        finally:
            if cap is not None:
                cap.release()
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

