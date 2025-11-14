"""
Main Flask application for Race to Master Prestige Leaderboard.
"""
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import threading
import time
import cv2
import numpy as np
import os
import json
from functools import wraps
from level_detector import LevelDetector
from stream_manager import StreamManager
from database import StreamDatabase

# Firebase Admin SDK for token verification
try:
    import firebase_admin
    from firebase_admin import credentials, auth
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("WARNING: firebase-admin not installed. Admin authentication will not work.")

app = Flask(__name__)
CORS(app)

# Initialize Firebase Admin SDK
firebase_app = None
if FIREBASE_AVAILABLE:
    try:
        # Try to initialize with service account key from environment variable or file
        # For production: Set FIREBASE_SERVICE_ACCOUNT_JSON environment variable with the JSON content
        # For local dev: Use firebase-service-account.json file
        service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
        
        if service_account_json:
            # Use environment variable (for production/deployment)
            import json
            cred_dict = json.loads(service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_app = firebase_admin.initialize_app(cred)
            print("✓ Firebase Admin SDK initialized (from environment variable)")
        else:
            # Try to load from file (for local development)
            cred_path = os.path.join(os.path.dirname(__file__), 'firebase-service-account.json')
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_app = firebase_admin.initialize_app(cred)
                print("✓ Firebase Admin SDK initialized (from file)")
            else:
                print("⚠ Firebase service account key not found.")
                print("   For local dev: Add firebase-service-account.json to project root")
                print("   For production: Set FIREBASE_SERVICE_ACCOUNT_JSON environment variable")
    except Exception as e:
        print(f"⚠ Firebase initialization failed: {e}")
        print("   Admin authentication will not work until Firebase is configured.")

# Authorized admin emails (whitelist)
# Add your email addresses here to restrict admin access
AUTHORIZED_ADMIN_EMAILS = [
    'n.dorfman00@gmail.com',
    # Add your authorized email addresses here
    # Example: 'your-email@gmail.com',
]

def require_auth(f):
    """Decorator to require Firebase authentication and authorized email."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not FIREBASE_AVAILABLE:
            return jsonify({'error': 'Firebase Admin SDK not installed. Run: pip install firebase-admin'}), 503
        
        if firebase_app is None:
            return jsonify({
                'error': 'Firebase not configured',
                'details': 'Firebase service account not configured. Set FIREBASE_SERVICE_ACCOUNT_JSON environment variable or add firebase-service-account.json file.'
            }), 503
        
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'No authorization token provided'}), 401
        
        token = auth_header.split('Bearer ')[1]
        
        try:
            # Verify the token
            decoded_token = auth.verify_id_token(token)
            user_email = decoded_token.get('email')
            
            # Check if email is authorized (if whitelist is configured)
            if AUTHORIZED_ADMIN_EMAILS and user_email not in AUTHORIZED_ADMIN_EMAILS:
                print(f"Unauthorized access attempt: {user_email}")
                return jsonify({'error': 'Unauthorized: Your email is not authorized to access the admin panel'}), 403
            
            # Token is valid and authorized, continue with the request
            request.user = decoded_token
            return f(*args, **kwargs)
        except Exception as e:
            print(f"Token verification failed: {e}")
            return jsonify({'error': 'Invalid or expired token'}), 401
    
    return decorated_function

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


@app.route('/favicon.ico')
def favicon():
    """Serve favicon with game controller emoji."""
    # Return emoji as SVG favicon
    from flask import Response
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y=".9em" font-size="90">🎮</text>
    </svg>'''
    return Response(svg, mimetype='image/svg+xml')

@app.route('/social.png')
def social_image():
    """Serve social sharing image."""
    # Try to serve from static folder, or return 404 if not found
    from flask import send_from_directory
    import os
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    if os.path.exists(os.path.join(static_path, 'social.png')):
        return send_from_directory(static_path, 'social.png')
    else:
        return jsonify({'error': 'Social image not found. Please create static/social.png'}), 404

@app.route('/')
def index():
    """Serve the public leaderboard page."""
    return render_template('index.html')


@app.route('/admin')
def admin_page():
    """Serve the admin page."""
    return render_template('admin.html')


@app.route('/test')
def test_page():
    """Serve the test page for development."""
    return render_template('test.html')


@app.route('/api/auth/verify', methods=['POST'])
def verify_token():
    """Verify Firebase ID token and check authorization."""
    if not FIREBASE_AVAILABLE:
        return jsonify({'error': 'Firebase Admin SDK not installed. Run: pip install firebase-admin'}), 503
    
    if firebase_app is None:
        return jsonify({
            'error': 'Firebase not configured',
            'details': 'firebase-service-account.json file not found. Please add it to the project root.'
        }), 503
    
    data = request.get_json()
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'No token provided'}), 400
    
    try:
        decoded_token = auth.verify_id_token(token)
        user_email = decoded_token.get('email')
        
        # Check if email is authorized (if whitelist is configured)
        if AUTHORIZED_ADMIN_EMAILS and user_email not in AUTHORIZED_ADMIN_EMAILS:
            print(f"Unauthorized access attempt: {user_email}")
            return jsonify({
                'valid': False,
                'error': 'Unauthorized: Your email is not authorized to access the admin panel',
                'email': user_email
            }), 403
        
        return jsonify({
            'valid': True,
            'uid': decoded_token['uid'],
            'email': user_email
        })
    except Exception as e:
        print(f"Token verification failed: {e}")
        return jsonify({'error': 'Invalid token', 'valid': False}), 401

@app.route('/api/streams/add', methods=['POST'])
@require_auth
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
@require_auth
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


@app.route('/api/streams/<int:stream_id>/annotated_frame', methods=['GET'])
def get_annotated_frame(stream_id):
    """Get the latest annotated frame for a stream."""
    # Try to get from memory first
    annotated_frame = stream_manager.get_annotated_frame(stream_id)
    
    # If not in memory, try to load from disk
    if annotated_frame is None:
        saved_frame_path = database.get_last_annotated_frame_path(stream_id)
        if saved_frame_path and os.path.exists(saved_frame_path):
            try:
                annotated_frame = cv2.imread(saved_frame_path)
            except Exception as e:
                print(f"Failed to load saved frame: {e}")
    
    if annotated_frame is None:
        return jsonify({'error': 'No annotated frame available'}), 404
    
    # Encode frame as JPEG
    ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ret:
        return jsonify({'error': 'Failed to encode frame'}), 500
    
    from flask import Response
    return Response(buffer.tobytes(), mimetype='image/jpeg')


@app.route('/api/streams/<int:stream_id>/original_frame', methods=['GET'])
def get_original_frame(stream_id):
    """Get the latest original (non-annotated) frame for a stream."""
    # Try to load from disk
    saved_frame_path = database.get_last_original_frame_path(stream_id)
    if saved_frame_path and os.path.exists(saved_frame_path):
        try:
            original_frame = cv2.imread(saved_frame_path)
            if original_frame is not None:
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', original_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ret:
                    from flask import Response
                    return Response(buffer.tobytes(), mimetype='image/jpeg')
        except Exception as e:
            print(f"Failed to load saved original frame: {e}")
    
    return jsonify({'error': 'No original frame available'}), 404


@app.route('/api/streams/<int:stream_id>/ocr_logs', methods=['GET'])
def get_ocr_logs(stream_id):
    """Get recent OCR logs for a stream."""
    # Try to get from memory first
    logs = stream_manager.get_ocr_logs(stream_id)
    
    # If not in memory, try to load from database
    if not logs:
        logs = database.get_last_ocr_logs(stream_id)
    
    return jsonify({'logs': logs})


@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """Get leaderboard of all streams sorted by progression."""
    limit = request.args.get('limit', 50, type=int)
    leaderboard = stream_manager.get_leaderboard(limit)
    
    # Merge with runtime status to get is_active
    manager_streams = {s['id']: s for s in stream_manager.get_all_streams_status()}
    
    # Enhance leaderboard entries with runtime status
    enhanced_leaderboard = []
    for entry in leaderboard:
        stream_id = entry.get('id')
        manager_status = manager_streams.get(stream_id, {})
        
        enhanced_entry = {
            **entry,
            'is_active': manager_status.get('is_active', False),
            'stream_url': entry.get('stream_url', '')
        }
        enhanced_leaderboard.append(enhanced_entry)
    
    return jsonify({
        'leaderboard': enhanced_leaderboard,
        'count': len(enhanced_leaderboard)
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
@require_auth
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
@require_auth
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
    print("Starting Race to Master Prestige Leaderboard...")
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
    
    # Start live check thread to periodically check if streams are live
    stream_manager.start_live_check()
    print("✓ Live stream checking enabled (checks every 60 seconds)")
    
    print("\nOpen http://localhost:5001 in your browser")
    print("API Endpoints:")
    print("  POST /api/streams/add - Add a stream to monitor")
    print("  POST /api/streams/remove - Remove a stream")
    print("  GET  /api/streams - Get all streams")
    print("  GET  /api/leaderboard - Get leaderboard")
    print()
    app.run(debug=True, host='0.0.0.0', port=5001)

