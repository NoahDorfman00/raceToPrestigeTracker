"""
Main Flask application for StreamWatcher.
"""
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import threading
import time
import cv2
import numpy as np
import os
import json
from level_detector import LevelDetector
from stream_manager import StreamManager
from database import StreamDatabase

app = Flask(__name__)
CORS(app)

# Initialize components
template_path = os.path.join('template_images', 'progression_template.png')
level_detector = LevelDetector(template_path=template_path)
database = StreamDatabase()
stream_manager = StreamManager(level_detector, database)

# Maximum number of streams that can be monitored simultaneously
# Each stream uses CPU/network resources, so limit to prevent overload
MAX_STREAMS = 10  # Adjust based on your system capabilities

# Check if Tesseract is available
if not level_detector.tesseract_available:
    print("WARNING: Tesseract OCR is not installed. Detection will not work.")


# Detection is now handled automatically by StreamManager for each stream


@app.route('/')
def index():
    """Serve the main webpage."""
    return render_template('index.html')


@app.route('/test')
def test_page():
    """Serve the test page for development."""
    return render_template('test.html')


@app.route('/api/streams/add', methods=['POST'])
def add_stream():
    """Add a stream to the monitoring list."""
    data = request.get_json() or {}
    stream_url = data.get('stream_url', '').strip() if data.get('stream_url') else ''
    streamer_name = data.get('streamer_name', '').strip() if data.get('streamer_name') else None
    
    if not stream_url:
        return jsonify({'error': 'Stream URL is required'}), 400
    
    # Check stream limit (use database count to avoid blocking)
    db_streams = database.get_all_active_streams()
    if len(db_streams) >= MAX_STREAMS:
        return jsonify({
            'error': f'Maximum number of streams ({MAX_STREAMS}) reached. Please remove a stream first.'
        }), 400
    
    try:
        stream_id = stream_manager.add_stream(stream_url, streamer_name)
        # Don't wait for stream to fully initialize - return immediately
        # Stream status will update once initialization completes
        return jsonify({
            'success': True,
            'stream_id': stream_id,
            'message': f'Stream added successfully. Initialization in progress...'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/streams/remove', methods=['POST'])
def remove_stream():
    """Remove a stream from the monitoring list."""
    data = request.get_json() or {}
    stream_id = data.get('stream_id')
    
    if stream_id is None:
        return jsonify({'error': 'stream_id is required'}), 400
    
    try:
        stream_manager.remove_stream(stream_id)
        return jsonify({
            'success': True,
            'message': 'Stream removed successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/streams', methods=['GET'])
def get_streams():
    """Get all monitored streams."""
    # Get streams from database (persistent) and merge with manager status (runtime)
    db_streams = database.get_all_active_streams()
    manager_streams = {s['id']: s for s in stream_manager.get_all_streams_status()}
    
    # Merge database data with manager runtime status
    merged_streams = []
    for db_stream in db_streams:
        stream_id = db_stream['id']
        manager_status = manager_streams.get(stream_id, {})
        
        # Merge: use manager status if available, otherwise use database
        merged = {
            'id': stream_id,
            'stream_url': db_stream['stream_url'],
            'streamer_name': db_stream['streamer_name'],
            'prestige': manager_status.get('prestige', db_stream.get('prestige', 0)),
            'level': manager_status.get('level', db_stream.get('level', 0)),
            'last_detected': manager_status.get('last_detected', db_stream.get('detected_at')),
            'is_active': manager_status.get('is_active', False),
            'error': manager_status.get('error')
        }
        merged_streams.append(merged)
    
    return jsonify({
        'streams': merged_streams,
        'count': len(merged_streams),
        'max_streams': MAX_STREAMS
    })


@app.route('/api/streams/<int:stream_id>', methods=['GET'])
def get_stream(stream_id):
    """Get status for a specific stream."""
    stream_info = stream_manager.get_stream_status(stream_id)
    if stream_info is None:
        return jsonify({'error': 'Stream not found'}), 404
    return jsonify(stream_info)


@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """Get leaderboard of all streams sorted by progression."""
    limit = request.args.get('limit', 50, type=int)
    leaderboard = stream_manager.get_leaderboard(limit)
    return jsonify({
        'leaderboard': leaderboard,
        'count': len(leaderboard)
    })


# Legacy endpoints for backward compatibility (optional - can be removed)
@app.route('/api/start', methods=['POST'])
def start_stream_legacy():
    """Legacy endpoint - adds stream instead of replacing."""
    return add_stream()


@app.route('/api/stop', methods=['POST'])
def stop_stream_legacy():
    """Legacy endpoint - requires stream_id in request."""
    data = request.get_json() or {}
    stream_id = data.get('stream_id')
    if stream_id:
        return remove_stream()
    return jsonify({'error': 'stream_id required'}), 400


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get system status and configuration."""
    streams = stream_manager.get_all_streams_status()
    return jsonify({
        'template_loaded': level_detector.template_gray is not None,
        'tesseract_available': level_detector.tesseract_available,
        'easyocr_available': level_detector.easyocr_available,
        'active_streams': len(streams),
        'max_streams': MAX_STREAMS,
        'progression_region_config': level_detector.progression_region_config,
        'level_region_config': level_detector.level_region_config,
        'prestige_region_config': level_detector.prestige_region_config
    })


@app.route('/api/update_config', methods=['POST'])
def update_config():
    """Update the template configuration file."""
    try:
        data = request.get_json()
        
        # Load existing config or create new
        config_path = 'template_config.json'
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        
        # Update progression region config
        if 'progression_region' in data:
            if 'progression_region' not in config:
                config['progression_region'] = {}
            config['progression_region'].update(data['progression_region'])
        
        # Update level region config
        if 'level_region' in data:
            if 'level_region' not in config:
                config['level_region'] = {}
            config['level_region'].update(data['level_region'])
        
        # Update prestige region config
        if 'prestige_region' in data:
            if 'prestige_region' not in config:
                config['prestige_region'] = {}
            config['prestige_region'].update(data['prestige_region'])
        
        # Save config file
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
        
        # Reload config in detector
        level_detector._load_config()
        
        return jsonify({
            'success': True,
            'message': 'Configuration updated successfully',
            'config': config
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generate_frames(stream_id: int = None):
    """Generate video frames with detection boxes drawn."""
    while True:
        # Only show preview if stream_id is explicitly provided
        # Don't auto-select - user must choose which stream to preview
        if stream_id is not None:
            frame = stream_manager.get_latest_frame(stream_id)
            if frame is not None:
                regions, detected_region = stream_manager.get_detection_regions(stream_id)
                stream_info = stream_manager.get_stream_status(stream_id)
                
                # Draw detection regions on frame
                annotated_frame = level_detector.draw_detection_regions(
                    frame, 
                    regions or [],
                    detected_region,
                    stream_info.get('level') if stream_info else None,
                    stream_info.get('prestige') if stream_info else None
                )
                
                # Add stream info text
                if stream_info:
                    info_text = f"{stream_info.get('streamer_name', 'Stream')} - P{stream_info.get('prestige', 0)} L{stream_info.get('level', 0)}"
                    cv2.putText(annotated_frame, info_text, (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                # Resize frame if too large (for better performance)
                height, width = annotated_frame.shape[:2]
                if width > 1280:
                    scale = 1280 / width
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    annotated_frame = cv2.resize(annotated_frame, (new_width, new_height))
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', annotated_frame, 
                                          [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # Stream exists but no frame yet
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, 'Waiting for stream frame...', (100, 240),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', placeholder)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            # No streams active
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, 'No streams active. Add a stream to monitor.', (50, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(placeholder, f'Max streams: {MAX_STREAMS}', (50, 260),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        time.sleep(0.033)  # ~30 FPS


@app.route('/video_feed')
@app.route('/video_feed/<int:stream_id>')
def video_feed(stream_id: int = None):
    """Video streaming route for debugging."""
    # Check for stop parameter
    stop = request.args.get('stop', 'false').lower() == 'true'
    if stop:
        stream_id = None
    
    return Response(generate_frames(stream_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/test_image', methods=['POST'])
def test_image():
    """Test detection on an uploaded image."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Read image from file
        file_bytes = file.read()
        nparr = np.frombuffer(file_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return jsonify({'error': 'Failed to decode image'}), 400
        
        # Run detection
        result, regions = level_detector.detect_multiple_regions(frame)
        
        # Debug: Print detection info
        print(f"Detection result: {result}")
        print(f"Regions found: {len(regions) if regions else 0}")
        
        # Draw detection regions on frame
        detected_region = regions[0] if regions and result else None
        annotated_frame = level_detector.draw_detection_regions(
            frame,
            regions if regions else [],
            detected_region,
            result.get('level') if result else None,
            result.get('prestige') if result else None
        )
        
        # Encode annotated frame as JPEG
        ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ret:
            return jsonify({'error': 'Failed to encode result image'}), 500
        
        import base64
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Also extract and return the level ROI for debugging
        level_roi_image = None
        prestige_roi_image = None
        if regions and len(regions) > 0:
            try:
                x, y, w, h = regions[0]
                # Use config-based regions
                level_region_x = x + int(w * level_detector.level_region_config['x_percent'])
                level_region_y = y + int(h * level_detector.level_region_config['y_percent'])
                level_region_w = int(w * level_detector.level_region_config['width_percent'])
                level_region_h = int(h * level_detector.level_region_config['height_percent'])
                
                # Ensure bounds
                level_region_x = max(0, level_region_x)
                level_region_y = max(0, level_region_y)
                level_region_w = min(frame.shape[1] - level_region_x, level_region_w)
                level_region_h = min(frame.shape[0] - level_region_y, level_region_h)
                
                level_roi = frame[level_region_y:level_region_y+level_region_h,
                                level_region_x:level_region_x+level_region_w]
                
                if level_roi.size > 0:
                    # Scale up for visibility
                    scaled_roi = cv2.resize(level_roi, (level_region_w * 4, level_region_h * 4))
                    ret_roi, buffer_roi = cv2.imencode('.jpg', scaled_roi, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    if ret_roi:
                        roi_base64 = base64.b64encode(buffer_roi).decode('utf-8')
                        level_roi_image = f'data:image/jpeg;base64,{roi_base64}'
                
                # Also extract prestige ROI for debugging
                prestige_region_x = x + int(w * level_detector.prestige_region_config['x_percent'])
                prestige_region_y = y + int(h * level_detector.prestige_region_config['y_percent'])
                prestige_region_w = int(w * level_detector.prestige_region_config['width_percent'])
                prestige_region_h = int(h * level_detector.prestige_region_config['height_percent'])
                
                prestige_region_x = max(0, prestige_region_x)
                prestige_region_y = max(0, prestige_region_y)
                prestige_region_w = min(frame.shape[1] - prestige_region_x, prestige_region_w)
                prestige_region_h = min(frame.shape[0] - prestige_region_y, prestige_region_h)
                
                prestige_roi = frame[prestige_region_y:prestige_region_y+prestige_region_h,
                                   prestige_region_x:prestige_region_x+prestige_region_w]
                
                if prestige_roi.size > 0:
                    scaled_prestige = cv2.resize(prestige_roi, (prestige_region_w * 3, prestige_region_h * 3))
                    ret_prestige, buffer_prestige = cv2.imencode('.jpg', scaled_prestige, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    if ret_prestige:
                        prestige_base64 = base64.b64encode(buffer_prestige).decode('utf-8')
                        prestige_roi_image = f'data:image/jpeg;base64,{prestige_base64}'
            except Exception as e:
                print(f"Error extracting ROI: {e}")
        
        return jsonify({
            'success': True,
            'result': result,
            'image': f'data:image/jpeg;base64,{img_base64}',
            'regions': regions,
            'level_roi': level_roi_image,  # Debug: show what region is being OCR'd
            'prestige_roi': prestige_roi_image  # Debug: show prestige region
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/test_video', methods=['POST'])
def test_video():
    """Test detection on an uploaded video file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    video_path = None
    try:
        # Save video temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            file.save(tmp_file.name)
            video_path = tmp_file.name
        
        # Open video with OpenCV
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            if video_path and os.path.exists(video_path):
                os.unlink(video_path)
            return jsonify({'error': 'Failed to open video'}), 400
        
        results = []
        frame_count = 0
        max_frames = 100  # Limit to first 100 frames for performance
        
        while frame_count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Run detection on every 10th frame to save processing
            if frame_count % 10 == 0:
                result, regions = level_detector.detect_multiple_regions(frame)
                if result:
                    results.append({
                        'frame': frame_count,
                        'level': result.get('level'),
                        'prestige': result.get('prestige', 0)
                    })
            
            frame_count += 1
        
        cap.release()
        if video_path and os.path.exists(video_path):
            os.unlink(video_path)  # Clean up temp file
        
        return jsonify({
            'success': True,
            'results': results,
            'total_frames': frame_count
        })
    except Exception as e:
        if video_path and os.path.exists(video_path):
            os.unlink(video_path)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting StreamWatcher...")
    print(f"Multi-stream monitoring enabled (max {MAX_STREAMS} streams)")
    
    # Check if template is loaded
    if level_detector.template_gray is not None:
        print(f"✓ Template loaded: {level_detector.template_path}")
    else:
        print(f"⚠ Warning: Template not found at {template_path}")
        print("   Please ensure progression_template.png exists in template_images/")
    
    # Check OCR availability
    if level_detector.tesseract_available:
        print("✓ Tesseract OCR available")
    else:
        print("⚠ Tesseract OCR not available - detection will not work")
    
    if level_detector.easyocr_available:
        print("✓ EasyOCR available (better for unusual fonts)")
    
    # Load existing streams from database
    existing_streams = database.get_all_active_streams()
    if existing_streams:
        print(f"✓ Found {len(existing_streams)} existing stream(s) in database")
        for stream in existing_streams:
            print(f"  - {stream.get('streamer_name', stream.get('stream_url'))}: P{stream.get('prestige', 0)} L{stream.get('level', 0)}")
            # Restore streams to monitoring
            try:
                # Use the stream ID from database to maintain consistency
                stream_id = stream.get('id')
                if stream_id:
                    # Check if stream already exists in manager
                    existing_status = stream_manager.get_stream_status(stream_id)
                    if not existing_status:
                        # Stream not in manager, add it
                        stream_manager.add_stream(stream['stream_url'], stream.get('streamer_name'))
                    else:
                        print(f"    Stream {stream_id} already active in manager")
            except Exception as e:
                print(f"  ⚠ Failed to restore stream {stream.get('id')}: {e}")
                import traceback
                traceback.print_exc()
    
    print("\nOpen http://localhost:5001 in your browser")
    print("API Endpoints:")
    print("  POST /api/streams/add - Add a stream to monitor")
    print("  POST /api/streams/remove - Remove a stream")
    print("  GET  /api/streams - Get all streams")
    print("  GET  /api/leaderboard - Get leaderboard")
    print()
    app.run(debug=True, host='0.0.0.0', port=5001)

