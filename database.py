"""
Simple file-based storage for stream data and level/prestige tracking.
"""
import json
import os
import time
from typing import Optional, Dict, List
from datetime import datetime


class StreamDatabase:
    """Manages JSON file storage for stream data."""
    
    def __init__(self, data_file: str = 'streams_data.json', frames_dir: str = 'annotated_frames'):
        """
        Initialize file storage.
        
        Args:
            data_file: Path to JSON data file
            frames_dir: Directory to store annotated frames
        """
        self.data_file = data_file
        self.frames_dir = frames_dir
        self._init_data_file()
        self._init_frames_dir()
    
    def _init_frames_dir(self):
        """Create frames directory if it doesn't exist."""
        if not os.path.exists(self.frames_dir):
            os.makedirs(self.frames_dir)
    
    def _init_data_file(self):
        """Create data file if it doesn't exist."""
        if not os.path.exists(self.data_file):
            data = {
                'streams': {},
                'next_id': 1
            }
            self._save_data(data)
    
    def _load_data(self) -> Dict:
        """Load data from file."""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'streams': {}, 'next_id': 1}
    
    def _save_data(self, data: Dict):
        """Save data to file."""
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_or_update_stream(self, stream_url: str, streamer_name: Optional[str] = None) -> int:
        """
        Add a new stream or update existing one.
        
        Args:
            stream_url: Stream URL
            streamer_name: Optional streamer name
            
        Returns:
            Stream ID
        """
        data = self._load_data()
        
        # Check if stream already exists
        for stream_id, stream_data in data['streams'].items():
            if stream_data['stream_url'] == stream_url:
                # Update existing stream
                stream_data['last_active'] = datetime.now().isoformat()
                stream_data['is_active'] = True
                if streamer_name:
                    stream_data['streamer_name'] = streamer_name
                self._save_data(data)
                return int(stream_id)
        
        # Create new stream
        stream_id = data['next_id']
        data['streams'][str(stream_id)] = {
            'id': stream_id,
            'stream_url': stream_url,
            'streamer_name': streamer_name or self._extract_streamer_name(stream_url),
            'created_at': datetime.now().isoformat(),
            'last_active': datetime.now().isoformat(),
            'is_active': True,
            'prestige': 0,
            'level': 0,
            'last_detected': None
        }
        data['next_id'] = stream_id + 1
        self._save_data(data)
        return stream_id
    
    def record_level_snapshot(self, stream_id: int, prestige: int, level: int, 
                             annotated_frame_path: Optional[str] = None,
                             original_frame_path: Optional[str] = None,
                             ocr_logs: Optional[List[Dict]] = None) -> bool:
        """
        Record a new level/prestige snapshot with annotated frame and OCR logs.
        Only records if it's different from the last snapshot.
        
        Args:
            stream_id: Stream ID
            prestige: Prestige level
            level: Level number
            annotated_frame_path: Path to saved annotated frame image
            original_frame_path: Path to saved original (non-annotated) frame image
            ocr_logs: List of OCR log entries
            
        Returns:
            True if snapshot was recorded, False if it was a duplicate
        """
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return False
        
        stream_data = data['streams'][stream_key]
        
        # Only update if different
        if stream_data['prestige'] == prestige and stream_data['level'] == level:
            return False
        
        # Update stream data
        stream_data['prestige'] = prestige
        stream_data['level'] = level
        stream_data['last_detected'] = datetime.now().isoformat()
        stream_data['last_active'] = datetime.now().isoformat()
        
        # Save annotated frame path, original frame path, and OCR logs
        if annotated_frame_path:
            stream_data['last_annotated_frame'] = annotated_frame_path
        if original_frame_path:
            stream_data['last_original_frame'] = original_frame_path
        if ocr_logs:
            stream_data['last_ocr_logs'] = ocr_logs
        
        self._save_data(data)
        return True
    
    def get_last_annotated_frame_path(self, stream_id: int) -> Optional[str]:
        """Get path to last annotated frame for a stream."""
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return None
        
        return data['streams'][stream_key].get('last_annotated_frame')
    
    def get_last_original_frame_path(self, stream_id: int) -> Optional[str]:
        """Get path to last original (non-annotated) frame for a stream."""
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return None
        
        return data['streams'][stream_key].get('last_original_frame')
    
    def get_last_ocr_logs(self, stream_id: int) -> List[Dict]:
        """Get last OCR logs for a stream."""
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return []
        
        return data['streams'][stream_key].get('last_ocr_logs', [])
    
    def get_latest_level(self, stream_id: int) -> Optional[Dict]:
        """
        Get the latest level/prestige for a stream.
        
        Args:
            stream_id: Stream ID
            
        Returns:
            Dict with prestige, level, detected_at, or None
        """
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return None
        
        stream_data = data['streams'][stream_key]
        return {
            'prestige': stream_data.get('prestige', 0),
            'level': stream_data.get('level', 0),
            'detected_at': stream_data.get('last_detected')
        }
    
    def get_stream_info(self, stream_id: int) -> Optional[Dict]:
        """
        Get stream information.
        
        Args:
            stream_id: Stream ID
            
        Returns:
            Dict with stream info, or None
        """
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key not in data['streams']:
            return None
        
        stream_data = data['streams'][stream_key]
        return {
            'id': stream_data['id'],
            'stream_url': stream_data['stream_url'],
            'streamer_name': stream_data.get('streamer_name'),
            'created_at': stream_data.get('created_at'),
            'last_active': stream_data.get('last_active'),
            'is_active': stream_data.get('is_active', True)
        }
    
    def get_all_active_streams(self) -> List[Dict]:
        """
        Get all active streams with their latest levels.
        
        Returns:
            List of stream dicts with latest level info
        """
        data = self._load_data()
        streams = []
        
        for stream_data in data['streams'].values():
            if stream_data.get('is_active', True):
                streams.append({
                    'id': stream_data['id'],
                    'stream_url': stream_data['stream_url'],
                    'streamer_name': stream_data.get('streamer_name') or self._extract_streamer_name(stream_data['stream_url']),
                    'last_active': stream_data.get('last_active'),
                    'prestige': stream_data.get('prestige', 0),
                    'level': stream_data.get('level', 0),
                    'detected_at': stream_data.get('last_detected')
                })
        
        # Sort by last_active (most recent first)
        streams.sort(key=lambda x: x['last_active'] or '', reverse=True)
        return streams
    
    def get_leaderboard(self, limit: int = 50) -> List[Dict]:
        """
        Get leaderboard sorted by progression (prestige, then level).
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of stream dicts sorted by progression
        """
        streams = self.get_all_active_streams()
        
        # Sort by prestige (desc), then level (desc)
        leaderboard = sorted(
            streams,
            key=lambda x: (x.get('prestige', 0), x.get('level', 0), x.get('detected_at') or ''),
            reverse=True
        )
        
        # Add rank and total_level
        for rank, stream in enumerate(leaderboard[:limit], 1):
            stream['rank'] = rank
            stream['total_level'] = stream.get('prestige', 0) * 1000 + stream.get('level', 0)
        
        return leaderboard[:limit]
    
    def deactivate_stream(self, stream_id: int):
        """Mark a stream as inactive."""
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key in data['streams']:
            data['streams'][stream_key]['is_active'] = False
            self._save_data(data)
    
    def delete_stream(self, stream_id: int):
        """Delete a stream."""
        data = self._load_data()
        stream_key = str(stream_id)
        
        if stream_key in data['streams']:
            del data['streams'][stream_key]
            self._save_data(data)
    
    def _extract_streamer_name(self, stream_url: str) -> str:
        """Extract streamer name from URL."""
        # Try to extract from twitch.tv URLs
        if 'twitch.tv' in stream_url:
            parts = stream_url.split('/')
            if len(parts) > 0:
                return parts[-1].split('?')[0]
        return stream_url

