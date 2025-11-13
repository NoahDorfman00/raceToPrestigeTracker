"""
Stream manager for handling multiple streams simultaneously.
"""
import threading
import time
from typing import Dict, Optional
from stream_capture import StreamCapture
from level_detector import LevelDetector
from database import StreamDatabase
import cv2
import numpy as np


class StreamInfo:
    """Information about a monitored stream."""
    
    def __init__(self, stream_id: int, stream_url: str, streamer_name: Optional[str] = None):
        self.stream_id = stream_id
        self.stream_url = stream_url
        self.streamer_name = streamer_name
        self.stream_capture: Optional[StreamCapture] = None
        self.detection_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.latest_frame: Optional[np.ndarray] = None
        self.prestige = 0
        self.level = 0
        self.last_detected: Optional[float] = None
        self.error: Optional[str] = None
        self.frame_lock = threading.Lock()
        self.detection_regions = []
        self.detected_region = None


class StreamManager:
    """Manages multiple streams and their detection."""
    
    def __init__(self, level_detector: LevelDetector, database: StreamDatabase):
        """
        Initialize stream manager.
        
        Args:
            level_detector: LevelDetector instance
            database: StreamDatabase instance
        """
        self.level_detector = level_detector
        self.database = database
        self.streams: Dict[int, StreamInfo] = {}
        self.lock = threading.Lock()
        self.detection_cooldown = 2.0  # Seconds between detections per stream
    
    def add_stream(self, stream_url: str, streamer_name: Optional[str] = None) -> int:
        """
        Add a new stream to monitor.
        
        Args:
            stream_url: Stream URL
            streamer_name: Optional streamer name
            
        Returns:
            Stream ID
        """
        # Add to database
        stream_id = self.database.add_or_update_stream(stream_url, streamer_name)
        
        # Load latest level from database
        latest = self.database.get_latest_level(stream_id)
        
        # Get streamer name from database if not provided
        if not streamer_name:
            stream_info_db = self.database.get_stream_info(stream_id)
            if stream_info_db:
                streamer_name = stream_info_db.get('streamer_name')
        
        with self.lock:
            if stream_id in self.streams:
                # Stream already exists, just restart it
                self._stop_stream_internal(stream_id)
            
            # Create stream info
            stream_info = StreamInfo(stream_id, stream_url, streamer_name)
            if latest:
                stream_info.prestige = latest['prestige']
                stream_info.level = latest['level']
            
            self.streams[stream_id] = stream_info
            
            # Start the stream in a background thread to avoid blocking
            def start_in_background():
                try:
                    self._start_stream_internal(stream_id)
                except Exception as e:
                    # If start fails, keep in database but mark error
                    print(f"Failed to start stream {stream_id}: {e}")
                    with self.lock:
                        if stream_id in self.streams:
                            self.streams[stream_id].error = str(e)
            
            start_thread = threading.Thread(target=start_in_background, daemon=True)
            start_thread.start()
        
        return stream_id
    
    def remove_stream(self, stream_id: int):
        """Remove and stop a stream."""
        with self.lock:
            if stream_id in self.streams:
                self._stop_stream_internal(stream_id)
                del self.streams[stream_id]
                self.database.delete_stream(stream_id)
    
    def _start_stream_internal(self, stream_id: int):
        """Internal method to start a stream."""
        stream_info = self.streams[stream_id]
        
        try:
            # Create stream capture
            stream_info.stream_capture = StreamCapture(stream_info.stream_url)
            stream_info.stream_capture.start()
            
            # Start detection thread
            stream_info.is_running = True
            stream_info.detection_thread = threading.Thread(
                target=self._detection_loop,
                args=(stream_id,),
                daemon=True
            )
            stream_info.detection_thread.start()
            
            print(f"Started monitoring stream {stream_id}: {stream_info.stream_url}")
        except Exception as e:
            stream_info.error = str(e)
            stream_info.is_running = False
            print(f"Error starting stream {stream_id}: {e}")
    
    def _stop_stream_internal(self, stream_id: int):
        """Internal method to stop a stream."""
        stream_info = self.streams[stream_id]
        
        stream_info.is_running = False
        
        if stream_info.stream_capture:
            stream_info.stream_capture.stop()
            stream_info.stream_capture = None
        
        if stream_info.detection_thread:
            stream_info.detection_thread.join(timeout=2)
            stream_info.detection_thread = None
        
        print(f"Stopped monitoring stream {stream_id}")
    
    def _detection_loop(self, stream_id: int):
        """Detection loop for a single stream."""
        stream_info = self.streams[stream_id]
        last_detection_time = 0
        frame_wait_count = 0
        
        while stream_info.is_running:
            if stream_info.stream_capture and stream_info.stream_capture.is_active():
                frame = stream_info.stream_capture.get_frame(timeout=0.5)
                if frame is not None:
                    frame_wait_count = 0
                    # Store latest frame
                    with stream_info.frame_lock:
                        stream_info.latest_frame = frame.copy()
                    
                    # Run detection periodically
                    current_time = time.time()
                    if current_time - last_detection_time >= self.detection_cooldown:
                        if self.level_detector.tesseract_available:
                            stream_info.error = None
                            try:
                                result, regions = self.level_detector.detect_multiple_regions(frame)
                                
                                with stream_info.frame_lock:
                                    stream_info.detection_regions = regions
                                
                                if result:
                                    new_prestige = result.get('prestige', 0)
                                    new_level = result.get('level')
                                    
                                    # Only update if different
                                    if (new_prestige != stream_info.prestige or 
                                        new_level != stream_info.level):
                                        
                                        # Record in database
                                        self.database.record_level_snapshot(
                                            stream_id, new_prestige, new_level
                                        )
                                        
                                        # Update stream info
                                        stream_info.prestige = new_prestige
                                        stream_info.level = new_level
                                        stream_info.last_detected = time.time()
                                        
                                        print(f"Stream {stream_id} ({stream_info.streamer_name or stream_info.stream_url}): "
                                              f"Prestige {new_prestige}, Level {new_level}")
                                        
                                        # Update detected region
                                        if regions and len(regions) > 0:
                                            with stream_info.frame_lock:
                                                stream_info.detected_region = regions[0]
                                else:
                                    with stream_info.frame_lock:
                                        stream_info.detected_region = None
                            except Exception as e:
                                stream_info.error = f"Detection error: {str(e)}"
                                print(f"Detection error for stream {stream_id}: {e}")
                        else:
                            stream_info.error = 'Tesseract OCR not available'
                        
                        last_detection_time = current_time
                else:
                    # No frame available, increase wait
                    frame_wait_count += 1
                    if frame_wait_count > 10:
                        # If no frames for 5 seconds, sleep longer
                        time.sleep(1)
                        frame_wait_count = 0
                    else:
                        time.sleep(0.1)
            else:
                # Stream not active, sleep longer
                time.sleep(2)
    
    def get_stream_status(self, stream_id: int) -> Optional[Dict]:
        """Get status for a specific stream."""
        # Quick check without holding lock too long
        stream_info = None
        with self.lock:
            if stream_id not in self.streams:
                return None
            stream_info = self.streams[stream_id]
        
        # Get frame lock separately to minimize lock contention
        try:
            with stream_info.frame_lock:
                is_active = stream_info.is_running and (
                    stream_info.stream_capture is not None and 
                    stream_info.stream_capture.is_active()
                )
        except:
            is_active = False
        
        return {
            'id': stream_id,
            'stream_url': stream_info.stream_url,
            'streamer_name': stream_info.streamer_name,
            'prestige': stream_info.prestige,
            'level': stream_info.level,
            'last_detected': stream_info.last_detected,
            'is_active': is_active,
            'error': stream_info.error
        }
    
    def get_all_streams_status(self) -> list:
        """Get status for all streams."""
        # Use a quick snapshot to avoid long lock holds
        stream_ids = []
        with self.lock:
            stream_ids = list(self.streams.keys())
        
        # Get status outside the lock to avoid blocking
        return [self.get_stream_status(stream_id) 
               for stream_id in stream_ids]
    
    def get_latest_frame(self, stream_id: int) -> Optional[np.ndarray]:
        """Get latest frame for a stream."""
        with self.lock:
            if stream_id not in self.streams:
                return None
            
            stream_info = self.streams[stream_id]
            with stream_info.frame_lock:
                return stream_info.latest_frame.copy() if stream_info.latest_frame is not None else None
    
    def get_detection_regions(self, stream_id: int) -> tuple:
        """Get detection regions for a stream."""
        with self.lock:
            if stream_id not in self.streams:
                return [], None
            
            stream_info = self.streams[stream_id]
            with stream_info.frame_lock:
                return stream_info.detection_regions, stream_info.detected_region
    
    def get_leaderboard(self, limit: int = 50) -> list:
        """Get leaderboard from database."""
        return self.database.get_leaderboard(limit)

