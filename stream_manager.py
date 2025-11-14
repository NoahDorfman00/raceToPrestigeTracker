"""
Stream manager for handling multiple streams simultaneously.
"""
import threading
import time
import subprocess
import os
import shutil
from typing import Dict, Optional, List
from datetime import datetime
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
        self.latest_annotated_frame: Optional[np.ndarray] = None  # Frame with detection boxes drawn
        self.prestige = 0
        self.level = 0
        self.last_detected: Optional[float] = None
        self.error: Optional[str] = None
        self.frame_lock = threading.Lock()
        self.detection_regions = []
        self.detected_region = None
        self.ocr_logs = []  # OCR logs for the most recent successful detection


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
        self.live_check_interval = 60.0  # Check if streams are live every 60 seconds
        self.live_check_thread: Optional[threading.Thread] = None
        self.live_check_running = False
    
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
            
            # Load saved annotated frame and OCR logs
            saved_frame_path = self.database.get_last_annotated_frame_path(stream_id)
            if saved_frame_path and os.path.exists(saved_frame_path):
                try:
                    saved_frame = cv2.imread(saved_frame_path)
                    if saved_frame is not None:
                        stream_info.latest_annotated_frame = saved_frame
                except Exception as e:
                    print(f"Failed to load saved frame for stream {stream_id}: {e}")
            
            saved_ocr_logs = self.database.get_last_ocr_logs(stream_id)
            if saved_ocr_logs:
                stream_info.ocr_logs = saved_ocr_logs
            
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
    
    def _check_stream_live(self, stream_url: str) -> bool:
        """
        Check if a stream is currently live (lightweight check).
        
        Args:
            stream_url: Stream URL or username
            
        Returns:
            True if stream is live, False otherwise
        """
        try:
            # Normalize URL
            url = stream_url.strip()
            if not url.startswith('http'):
                url = f'https://www.twitch.tv/{url}'
            
            # Find streamlink
            streamlink_path = self._find_streamlink()
            if not streamlink_path:
                print(f"ERROR: streamlink not found. Cannot check if stream is live: {url}")
                return False
            
            # Use streamlink to check if stream is available (lightweight)
            # This doesn't open the full stream, just checks availability
            cmd = [streamlink_path, '--json', url, 'best']
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                text=True
            )
            
            # Log the result for debugging
            if result.returncode == 0:
                print(f"✓ Stream is LIVE: {url}")
                return True
            else:
                # Only log if it's not a simple "not live" error
                if result.stderr and 'No playable streams found' not in result.stderr:
                    print(f"✗ Stream check failed for {url}: {result.stderr[:200]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"✗ Stream check TIMED OUT: {stream_url}")
            return False
        except Exception as e:
            print(f"✗ Error checking stream ({stream_url}): {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _start_stream_internal(self, stream_id: int):
        """Internal method to start a stream."""
        stream_info = self.streams[stream_id]
        
        print(f"Attempting to start stream {stream_id}: {stream_info.stream_url}")
        
        # Check if stream is live before starting capture
        is_live = self._check_stream_live(stream_info.stream_url)
        if not is_live:
            print(f"Stream {stream_id} ({stream_info.streamer_name or stream_info.stream_url}) is not live, skipping capture")
            stream_info.error = "Stream is not live"
            return
        
        try:
            # Create stream capture
            print(f"Stream {stream_id} is live, starting capture...")
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
            
            print(f"✓ Started monitoring stream {stream_id}: {stream_info.stream_url}")
        except Exception as e:
            stream_info.error = str(e)
            stream_info.is_running = False
            print(f"✗ Error starting stream {stream_id}: {e}")
            import traceback
            traceback.print_exc()
    
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
                                
                                # Only save frames when we have a complete detection:
                                # 1. Progression screen detected (result is not None)
                                # 2. Level successfully extracted (new_level is not None and in valid range)
                                # 3. Prestige successfully extracted (new_prestige is not None, can be 0)
                                # 4. Valid progression region exists
                                if result:
                                    new_prestige = result.get('prestige')
                                    new_level = result.get('level')
                                    ocr_text = result.get('prestige_ocr_text', '')
                                    
                                    # Validate that we have all required detections
                                    # Level must be valid (1-55)
                                    if new_level is None:
                                        print(f"Stream {stream_id}: Skipping frame save - no level detected (result exists but level is None)")
                                        last_detection_time = current_time
                                        continue
                                    
                                    # Prestige should always be set (defaults to 0 if not detected)
                                    # But ensure it's a valid number, not None
                                    if new_prestige is None:
                                        new_prestige = 0
                                    
                                    # Additional validation: ensure we have a valid progression region
                                    # Only save if we have regions and the first region is the progression screen
                                    if not regions or len(regions) == 0:
                                        print(f"Stream {stream_id}: Skipping frame save - no progression region detected")
                                        last_detection_time = current_time
                                        continue
                                    
                                    # Final validation: ensure level is in valid range (should already be validated by detect_multiple_regions)
                                    min_level, max_level = self.level_detector.valid_level_range
                                    if not (min_level <= new_level <= max_level):
                                        print(f"Stream {stream_id}: Skipping frame save - level {new_level} out of valid range [{min_level}, {max_level}]")
                                        last_detection_time = current_time
                                        continue
                                    
                                    # All validations passed - this is a complete detection with progression, level, and prestige
                                    # We will ALWAYS save the frame and OCR logs when we have a complete detection
                                    # Progression validation only determines if we UPDATE the stored values
                                    print(f"Stream {stream_id}: Complete detection - P{new_prestige} L{new_level} - saving frame and OCR logs")
                                    
                                    # Validate that level/prestige hasn't gone down
                                    # Calculate total progression: prestige * 1000 + level
                                    current_total = stream_info.prestige * 1000 + (stream_info.level or 0)
                                    new_total = new_prestige * 1000 + (new_level or 0)
                                    
                                    # Check if this is a valid progression
                                    # Allow if:
                                    # 1. Total progression increased, OR
                                    # 2. Prestige increased (rollover case: P1 L55 -> P2 L1)
                                    is_valid_progression = False
                                    
                                    if new_total > current_total:
                                        # Normal progression: total level increased
                                        is_valid_progression = True
                                    elif new_prestige > stream_info.prestige:
                                        # Prestige rollover: prestige increased (e.g., P1 L55 -> P2 L1)
                                        # This is valid even if total is slightly lower
                                        is_valid_progression = True
                                    elif new_total == current_total:
                                        # Same level - this is okay, might be re-detection
                                        is_valid_progression = True
                                    else:
                                        # Level went down without prestige increase - invalid
                                        print(f"Stream {stream_id}: Invalid progression detected - "
                                              f"Current: P{stream_info.prestige} L{stream_info.level} ({current_total}), "
                                              f"Detected: P{new_prestige} L{new_level} ({new_total}) - "
                                              f"Will save frame/OCR but not update stored values")
                                        is_valid_progression = False
                                    
                                    # Create annotated frame for display with all annotation boxes
                                    annotated_frame = frame.copy()
                                    if regions and len(regions) > 0:
                                        # Use the first region (progression screen) as the detected region
                                        # This ensures all annotation boxes are drawn
                                        progression_region = regions[0]
                                        annotated_frame = self.level_detector.draw_detection_regions(
                                            annotated_frame,
                                            regions,
                                            progression_region,  # Always use the progression region as detected
                                            new_level,
                                            new_prestige
                                        )
                                    
                                    # Store OCR logs for this detection
                                    ocr_log_entry = {
                                        'timestamp': time.time(),
                                        'prestige': new_prestige,
                                        'level': new_level,
                                        'ocr_text': ocr_text,
                                        'detected': True
                                    }
                                    
                                    # Save both annotated and original frames to disk
                                    timestamp = int(time.time())
                                    annotated_filename = f"stream_{stream_id}_{timestamp}_annotated.jpg"
                                    original_filename = f"stream_{stream_id}_{timestamp}_original.jpg"
                                    annotated_frame_path = os.path.join(self.database.frames_dir, annotated_filename)
                                    original_frame_path = os.path.join(self.database.frames_dir, original_filename)
                                    
                                    # Remove old frames if they exist
                                    old_annotated_path = self.database.get_last_annotated_frame_path(stream_id)
                                    if old_annotated_path and os.path.exists(old_annotated_path):
                                        try:
                                            os.remove(old_annotated_path)
                                        except:
                                            pass
                                    
                                    old_original_path = self.database.get_last_original_frame_path(stream_id)
                                    if old_original_path and os.path.exists(old_original_path):
                                        try:
                                            os.remove(old_original_path)
                                        except:
                                            pass
                                    
                                    # Save both frames to disk
                                    try:
                                        success_annotated = cv2.imwrite(annotated_frame_path, annotated_frame)
                                        success_original = cv2.imwrite(original_frame_path, frame)
                                        if not success_annotated or not success_original:
                                            print(f"Stream {stream_id}: WARNING - Failed to save frames to disk")
                                            print(f"  Annotated: {success_annotated}, Original: {success_original}")
                                            print(f"  Paths: {annotated_frame_path}, {original_frame_path}")
                                        else:
                                            print(f"Stream {stream_id}: Successfully saved frames to disk")
                                    except Exception as e:
                                        print(f"Stream {stream_id}: ERROR saving frames - {e}")
                                        import traceback
                                        traceback.print_exc()
                                    
                                    # Store annotated frame and OCR logs only for successful detections
                                    with stream_info.frame_lock:
                                        stream_info.latest_annotated_frame = annotated_frame.copy()
                                        # Store OCR logs for this detection (replace previous logs)
                                        stream_info.ocr_logs = [ocr_log_entry]
                                    
                                    # Always save frame and OCR logs to database for persistence
                                    # Update database with frame paths and OCR logs (even if level hasn't changed)
                                    try:
                                        data = self.database._load_data()
                                        stream_key = str(stream_id)
                                        if stream_key in data['streams']:
                                            stream_data = data['streams'][stream_key]
                                            stream_data['last_annotated_frame'] = annotated_frame_path
                                            stream_data['last_original_frame'] = original_frame_path
                                            stream_data['last_ocr_logs'] = [ocr_log_entry]
                                            stream_data['last_active'] = datetime.now().isoformat()
                                            self.database._save_data(data)
                                            print(f"Stream {stream_id}: Successfully saved frame paths and OCR logs to database")
                                        else:
                                            print(f"Stream {stream_id}: WARNING - Stream {stream_key} not found in database")
                                    except Exception as e:
                                        print(f"Stream {stream_id}: ERROR saving to database - {e}")
                                        import traceback
                                        traceback.print_exc()
                                    
                                    # Only update level/prestige if different
                                    if (new_prestige != stream_info.prestige or 
                                        new_level != stream_info.level):
                                        
                                        # Record level snapshot in database
                                        self.database.record_level_snapshot(
                                            stream_id, new_prestige, new_level,
                                            annotated_frame_path=annotated_frame_path,
                                            original_frame_path=original_frame_path,
                                            ocr_logs=[ocr_log_entry]
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
                                    # No detection - clear detected region but keep last annotated frame
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
    
    def get_annotated_frame(self, stream_id: int) -> Optional[np.ndarray]:
        """Get latest annotated frame for a stream."""
        with self.lock:
            if stream_id not in self.streams:
                return None
            
            stream_info = self.streams[stream_id]
            with stream_info.frame_lock:
                return stream_info.latest_annotated_frame.copy() if stream_info.latest_annotated_frame is not None else None
    
    def get_ocr_logs(self, stream_id: int) -> List[Dict]:
        """Get recent OCR logs for a stream."""
        with self.lock:
            if stream_id not in self.streams:
                return []
            
            stream_info = self.streams[stream_id]
            with stream_info.frame_lock:
                return stream_info.ocr_logs.copy()
    
    def get_leaderboard(self, limit: int = 50) -> list:
        """Get leaderboard from database."""
        return self.database.get_leaderboard(limit)
    
    def _live_check_loop(self):
        """Background thread to periodically check if streams are live."""
        while self.live_check_running:
            try:
                # Get all stream IDs
                stream_ids = []
                with self.lock:
                    stream_ids = list(self.streams.keys())
                
                for stream_id in stream_ids:
                    with self.lock:
                        if stream_id not in self.streams:
                            continue
                        stream_info = self.streams[stream_id]
                    
                    # Check if stream is live
                    is_live = self._check_stream_live(stream_info.stream_url)
                    
                    with self.lock:
                        if stream_id not in self.streams:
                            continue
                        stream_info = self.streams[stream_id]
                        
                        if is_live:
                            # Stream is live - start capture if not already running
                            if not stream_info.is_running:
                                print(f"Stream {stream_id} is now live, starting capture")
                                stream_info.error = None
                                # Start in background to avoid blocking
                                threading.Thread(
                                    target=self._start_stream_internal,
                                    args=(stream_id,),
                                    daemon=True
                                ).start()
                        else:
                            # Stream is not live - stop capture if running
                            if stream_info.is_running:
                                print(f"Stream {stream_id} is no longer live, stopping capture")
                                self._stop_stream_internal(stream_id)
                                stream_info.error = "Stream is not live"
                
                # Sleep before next check
                time.sleep(self.live_check_interval)
            except Exception as e:
                print(f"Error in live check loop: {e}")
                time.sleep(self.live_check_interval)
    
    def start_live_check(self):
        """Start the background thread that checks if streams are live."""
        if self.live_check_running:
            return
        
        self.live_check_running = True
        self.live_check_thread = threading.Thread(target=self._live_check_loop, daemon=True)
        self.live_check_thread.start()
        print("Started live stream checking")
    
    def stop_live_check(self):
        """Stop the background thread that checks if streams are live."""
        self.live_check_running = False
        if self.live_check_thread:
            self.live_check_thread.join(timeout=2)

