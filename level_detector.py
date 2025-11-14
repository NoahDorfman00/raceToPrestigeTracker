"""
Computer vision module to detect level and prestige from Call of Duty gameplay.
"""
import cv2
import numpy as np
import pytesseract
import re
import shutil
import os
import json
from typing import Optional, Dict, Tuple, List
from PIL import Image

# Try to import EasyOCR (optional, better for unusual fonts)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None


class LevelDetector:
    """Detects level and prestige information from game frames."""
    
    def __init__(self, template_path: Optional[str] = None):
        """
        Initialize the level detector.
        
        Args:
            template_path: Path to template image of the progression screen
        """
        # Configure tesseract for better text recognition
        # Use PSM 7 for single line of text (level numbers are large and isolated)
        # Use PSM 8 for single word
        # Use PSM 6 for single uniform block of text
        # Level range: 1-55, Prestige range: 0-10
        self.tesseract_config_level = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'  # For large level numbers
        self.tesseract_config_text = r'--oem 3 --psm 6'  # For rank/prestige text
        
        # Valid ranges for validation
        self.valid_level_range = (1, 55)
        self.valid_prestige_range = (0, 10)
        self.tesseract_available = self._check_tesseract()
        
        # Initialize EasyOCR if available (better for unusual fonts)
        # Can be disabled via DISABLE_EASYOCR env var to save ~1-2GB RAM
        self.easyocr_reader = None
        self.easyocr_available = False
        if EASYOCR_AVAILABLE and os.environ.get('DISABLE_EASYOCR', '').lower() != 'true':
            try:
                # Initialize EasyOCR reader (English only for speed)
                print("Initializing EasyOCR (this may take a moment on first run)...")
                print("NOTE: EasyOCR uses ~1-2GB RAM. Set DISABLE_EASYOCR=true to save memory.")
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False)
                self.easyocr_available = True
                print("EasyOCR initialized successfully")
            except Exception as e:
                print(f"EasyOCR initialization failed: {e}")
                print("Falling back to Tesseract only")
                self.easyocr_available = False
        elif os.environ.get('DISABLE_EASYOCR', '').lower() == 'true':
            print("EasyOCR disabled via DISABLE_EASYOCR environment variable (saves ~1-2GB RAM)")
        
        # Template matching
        self.template = None
        self.template_gray = None
        self.template_gray_focused = None  # Focused template for matching
        self.template_path = template_path
        self.template_focus_offset_x = 0  # Offset of focused template within original
        self.template_focus_offset_y = 0
        
        # Region configuration (can be overridden by config file)
        self.progression_region_config = {
            'x_percent': 0.33,  # Middle third of screen
            'y_percent': 0.0,   # Top portion
            'width_percent': 0.34,
            'height_percent': 0.15
        }
        self.level_region_config = {
            'x_percent': 0.3,
            'y_percent': 0.45,
            'width_percent': 0.4,
            'height_percent': 0.2
        }
        self.prestige_region_config = {
            'x_percent': 0.3,
            'y_percent': 0.3,
            'width_percent': 0.5,
            'height_percent': 0.15
        }
        
        # Load configuration from file if it exists
        self._load_config()
        
        if template_path and os.path.exists(template_path):
            self.load_template(template_path)
        
        if not self.tesseract_available:
            print("WARNING: Tesseract OCR is not installed or not in PATH.")
            print("Please install Tesseract:")
            print("  macOS: brew install tesseract")
            print("  Linux: sudo apt-get install tesseract-ocr")
            print("  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
            print("Detection will not work until Tesseract is installed.")
    
    def _check_tesseract(self) -> bool:
        """Check if Tesseract is installed and available."""
        try:
            # Try to find tesseract in PATH
            tesseract_path = shutil.which('tesseract')
            if tesseract_path:
                # Try to run tesseract to verify it works
                pytesseract.get_tesseract_version()
                return True
            return False
        except (pytesseract.TesseractNotFoundError, Exception):
            return False
    
    def _load_config(self):
        """Load region configuration from JSON file if it exists."""
        config_path = 'template_config.json'
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    
                if 'level_region' in config:
                    self.level_region_config.update(config['level_region'])
                    print(f"Loaded level region config: {self.level_region_config}")
                
                if 'progression_region' in config:
                    self.progression_region_config.update(config['progression_region'])
                    print(f"Loaded progression region config: {self.progression_region_config}")
                
                if 'prestige_region' in config:
                    self.prestige_region_config.update(config['prestige_region'])
                    print(f"Loaded prestige region config: {self.prestige_region_config}")
                    
            except Exception as e:
                print(f"Error loading config file: {e}")
                print("Using default region configurations")
        
    def preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Preprocess frame for better text detection.
        
        Args:
            frame: Input frame from stream
            
        Returns:
            Preprocessed frame
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Apply threshold to make text stand out
        # This works well for white text on dark backgrounds (common in CoD UI)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        
        # Apply some noise reduction
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)
        
        return denoised
    
    def detect_ui_region(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the region where level/prestige info typically appears.
        In Call of Duty, this is usually in the top-left or top-center area.
        
        Args:
            frame: Input frame
            
        Returns:
            Tuple of (x, y, width, height) for the UI region, or None
        """
        height, width = frame.shape[:2]
        
        # Define regions where level/prestige typically appears
        # Top-left region (common for player stats)
        top_left_region = (0, 0, width // 3, height // 4)
        
        # Top-center region (sometimes used for kill feed with level)
        top_center_region = (width // 4, 0, width // 2, height // 4)
        
        # Return the top-left region as default
        # You may need to adjust this based on the specific CoD game
        return top_left_region
    
    def extract_text_from_region(self, frame: np.ndarray, region: Tuple[int, int, int, int], 
                                 config: Optional[str] = None) -> str:
        """
        Extract text from a specific region of the frame.
        
        Args:
            frame: Preprocessed frame
            region: (x, y, width, height) region to extract from
            config: Optional Tesseract config (defaults to text config)
            
        Returns:
            Extracted text string, or empty string if OCR fails
        """
        if not self.tesseract_available:
            return ""
        
        if config is None:
            config = self.tesseract_config_text
        
        try:
            x, y, w, h = region
            roi = frame[y:y+h, x:x+w]
            
            # Convert to PIL Image for tesseract
            pil_image = Image.fromarray(roi)
            
            # Extract text
            text = pytesseract.image_to_string(pil_image, config=config)
            
            return text.strip()
        except (pytesseract.TesseractNotFoundError, Exception) as e:
            print(f"OCR error: {e}")
            return ""
    
    def parse_level_prestige(self, text: str) -> Optional[Dict[str, int]]:
        """
        Parse level and prestige from extracted text.
        
        Looks for patterns like:
        - "Prestige 5 Level 55"
        - "P5 L55"
        - "5-55" (prestige-level)
        - "55" (just level, no prestige)
        
        Args:
            text: Extracted text string
            
        Returns:
            Dictionary with 'level' and 'prestige' keys, or None if not found
        """
        if not text:
            return None
        
        # Pattern 1: "Prestige X Level Y" or "P X L Y"
        pattern1 = re.compile(r'[Pp]restige?\s*(\d+).*?[Ll]evel?\s*(\d+)', re.IGNORECASE)
        match = pattern1.search(text)
        if match:
            return {
                'prestige': int(match.group(1)),
                'level': int(match.group(2))
            }
        
        # Pattern 2: "P5 L55" or "P 5 L 55"
        pattern2 = re.compile(r'[Pp]\s*(\d+).*?[Ll]\s*(\d+)', re.IGNORECASE)
        match = pattern2.search(text)
        if match:
            return {
                'prestige': int(match.group(1)),
                'level': int(match.group(2))
            }
        
        # Pattern 3: "5-55" (prestige-level format)
        pattern3 = re.compile(r'(\d+)\s*[-]\s*(\d+)')
        match = pattern3.search(text)
        if match:
            # First number could be prestige, second is level
            # Or vice versa - we'll assume first is prestige if > 10
            num1, num2 = int(match.group(1)), int(match.group(2))
            if num1 <= 10 and num2 > 10:
                return {'prestige': num1, 'level': num2}
            elif num2 <= 10 and num1 > 10:
                return {'prestige': num2, 'level': num1}
        
        # Pattern 4: Just a level number (no prestige)
        pattern4 = re.compile(r'\b(\d{2,3})\b')
        matches = pattern4.findall(text)
        if matches:
            level = int(matches[-1])  # Take the last number (likely the level)
            if 1 <= level <= 1000:  # Reasonable level range
                return {'prestige': 0, 'level': level}
        
        return None
    
    def detect(self, frame: np.ndarray) -> Optional[Dict[str, int]]:
        """
        Main detection method - processes a frame and returns level/prestige.
        
        Args:
            frame: Frame from stream capture
            
        Returns:
            Dictionary with 'level' and 'prestige' keys, or None if not detected
        """
        if frame is None:
            return None
        
        # Preprocess frame
        processed = self.preprocess_frame(frame)
        
        # Detect UI region
        region = self.detect_ui_region(processed)
        if not region:
            return None
        
        # Extract text from region
        text = self.extract_text_from_region(processed, region)
        
        # Parse level and prestige
        result = self.parse_level_prestige(text)
        
        return result
    
    def load_template(self, template_path: str):
        """
        Load a template image for the progression screen.
        Optionally creates a smaller, more focused template from the center region.
        
        Args:
            template_path: Path to the template image file
        """
        try:
            self.template = cv2.imread(template_path)
            if self.template is None:
                print(f"Failed to load template from {template_path}")
                return False
            
            self.template_gray = cv2.cvtColor(self.template, cv2.COLOR_BGR2GRAY)
            self.template_path = template_path
            
            template_h, template_w = self.template_gray.shape[:2]
            
            # Store original dimensions
            orig_h, orig_w = template_h, template_w
            
            # Create a more focused template from the center region
            # This makes matching more flexible by focusing on the core circular element
            # Use config if available, otherwise default to 15% margin
            margin_x_percent = self.template_focus_offset_x if hasattr(self, 'template_focus_offset_x') else 0.15
            margin_y_percent = self.template_focus_offset_y if hasattr(self, 'template_focus_offset_y') else 0.15
            
            # Load from config if available
            config_path = 'template_config.json'
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        if 'template_focus' in config:
                            margin_x_percent = config['template_focus'].get('center_margin_x_percent', 0.15)
                            margin_y_percent = config['template_focus'].get('center_margin_y_percent', 0.15)
                except:
                    pass
            
            center_margin_x = int(template_w * margin_x_percent)
            center_margin_y = int(template_h * margin_y_percent)
            focused_w = template_w - (2 * center_margin_x)
            focused_h = template_h - (2 * center_margin_y)
            
            # Store the focused template for matching
            self.template_gray_focused = self.template_gray[
                center_margin_y:center_margin_y+focused_h,
                center_margin_x:center_margin_x+focused_w
            ].copy()
            
            # Store the focus offset (needed to adjust match coordinates)
            self.template_focus_offset_x = center_margin_x
            self.template_focus_offset_y = center_margin_y
            
            # Store original template dimensions for region calculations
            self.original_template_width = orig_w
            self.original_template_height = orig_h
            
            print(f"Template loaded successfully: {focused_w}x{focused_h} (focused from {orig_w}x{orig_h})")
            return True
        except Exception as e:
            print(f"Error loading template: {e}")
            return False
    
    def detect_progression_screen(self, frame: np.ndarray, threshold: float = 0.6) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the progression screen using template matching with scale variations.
        Only searches the middle vertical third of the frame to save resources.
        Uses multiple scales to handle template size variations.
        
        Args:
            frame: Original frame from stream
            threshold: Matching threshold (0.0 to 1.0, lower = more flexible)
            
        Returns:
            Region (x, y, width, height) of the progression UI, or None
        """
        if frame is None:
            return None
        
        # Use focused template for matching if available, otherwise use full template
        matching_template = self.template_gray_focused if self.template_gray_focused is not None else self.template_gray
        if matching_template is None:
            return None
        
        # Get frame dimensions
        frame_h, frame_w = frame.shape[:2]
        template_h, template_w = matching_template.shape[:2]
        
        # Restrict search to middle vertical third of screen (horizontally divided into 3 sections)
        # This saves resources since the progression screen always appears in the center
        # Middle third horizontally (center column), full height vertically
        search_x = int(frame_w / 3)  # Start at 1/3 from left
        search_y = 0  # Start at top
        search_w = int(frame_w / 3)  # Middle third width
        search_h = frame_h  # Use full height
        
        # Check if template is larger than search region - if so, expand search region
        if template_w > search_w or template_h > search_h:
            # Template is larger than middle third, expand to full frame
            search_x = 0
            search_y = 0
            search_w = frame_w
            search_h = frame_h
        
        # Final safety check: ensure template fits in search region
        if template_w > search_w or template_h > search_h:
            print(f"Warning: Template ({template_w}x{template_h}) is larger than frame ({frame_w}x{frame_h})")
            return None
        
        # Crop to search region
        search_region = frame[search_y:search_y+search_h, search_x:search_x+search_w]
        
        # Convert to grayscale for matching
        search_gray = cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)
        
        # Try multiple scales to handle size variations
        # The progression screen might appear at slightly different sizes
        scales = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]  # Try 85% to 115% of template size
        best_match = None
        best_score = threshold
        best_scale = 1.0
        
        try:
            for scale in scales:
                # Resize template for this scale
                scaled_w = int(template_w * scale)
                scaled_h = int(template_h * scale)
                
                # Skip if scaled template is larger than search region
                if scaled_w > search_w or scaled_h > search_h:
                    continue
                
                # Skip if scaled template is too small
                if scaled_w < 50 or scaled_h < 50:
                    continue
                
                scaled_template = cv2.resize(matching_template, (scaled_w, scaled_h), 
                                            interpolation=cv2.INTER_CUBIC)
                
                # Perform template matching
                result = cv2.matchTemplate(search_gray, scaled_template, cv2.TM_CCOEFF_NORMED)
                
                # Find the best match for this scale
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                
                # Keep track of best match across all scales
                if max_val > best_score:
                    best_score = max_val
                    best_match = max_loc
                    best_scale = scale
            
            # Check if best match is good enough
            if best_match is not None and best_score >= threshold:
                # Calculate absolute coordinates
                # Adjust for search region offset
                x = best_match[0] + search_x
                y = best_match[1] + search_y
                
                # If we used a focused template, adjust coordinates to account for the crop
                if self.template_gray_focused is not None:
                    x -= self.template_focus_offset_x
                    y -= self.template_focus_offset_y
                
                # Return region based on original template size (for consistent extraction)
                orig_template = cv2.cvtColor(self.template, cv2.COLOR_BGR2GRAY)
                orig_h, orig_w = orig_template.shape[:2]
                w, h = orig_w, orig_h
                
                # Ensure coordinates are valid
                x = max(0, x)
                y = max(0, y)
                
                print(f"Template matched with score {best_score:.2f} at scale {best_scale:.2f}")
                return (x, y, w, h)
            else:
                print(f"Template matching failed - best score: {best_score:.2f} (threshold: {threshold})")
                
        except cv2.error as e:
            print(f"Template matching error: {e}")
            return None
        
        return None
    
    def extract_level_from_progression_screen(self, frame: np.ndarray, region: Tuple[int, int, int, int]) -> Optional[int]:
        """
        Extract the level number from the progression screen.
        The level appears as a large, bold number in the center of the circular UI.
        
        Args:
            frame: Original frame
            region: Region containing the progression screen (from template match)
            
        Returns:
            Level number, or None if not found
        """
        if not self.tesseract_available or frame is None or region is None:
            return None
        
        x, y, w, h = region
        
        # Use configuration to determine level region (percentages relative to template)
        # This allows precise control via template_config.json
        level_region_x = x + int(w * self.level_region_config['x_percent'])
        level_region_y = y + int(h * self.level_region_config['y_percent'])
        level_region_w = int(w * self.level_region_config['width_percent'])
        level_region_h = int(h * self.level_region_config['height_percent'])
        
        # Ensure we don't go out of bounds
        level_region_x = max(0, level_region_x)
        level_region_y = max(0, level_region_y)
        level_region_w = min(frame.shape[1] - level_region_x, level_region_w)
        level_region_h = min(frame.shape[0] - level_region_y, level_region_h)
        
        # Extract the level region
        level_roi = frame[level_region_y:level_region_y+level_region_h, 
                         level_region_x:level_region_x+level_region_w]
        
        if level_roi.size == 0:
            print("Level ROI is empty")
            return None
        
        # Try multiple preprocessing methods for better OCR
        results = []
        
        # Method 1: Adaptive threshold
        gray = cv2.cvtColor(level_roi, cv2.COLOR_BGR2GRAY)
        thresh1 = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        if np.mean(thresh1) < 128:
            thresh1 = cv2.bitwise_not(thresh1)
        
        # Method 2: Simple threshold
        _, thresh2 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh2) < 128:
            thresh2 = cv2.bitwise_not(thresh2)
        
        # Method 3: High contrast threshold (for white text)
        _, thresh3 = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        
        # Try each preprocessing method
        for i, processed in enumerate([thresh1, thresh2, thresh3]):
            try:
                # Scale up for better OCR (larger numbers are easier to read)
                scale_factor = 4
                enlarged = cv2.resize(processed, 
                                     (level_region_w * scale_factor, level_region_h * scale_factor),
                                     interpolation=cv2.INTER_CUBIC)
                
                # Apply additional sharpening
                kernel = np.array([[-1,-1,-1],
                                   [-1, 9,-1],
                                   [-1,-1,-1]])
                sharpened = cv2.filter2D(enlarged, -1, kernel)
                
                # Extract text
                pil_image = Image.fromarray(sharpened)
                text = pytesseract.image_to_string(pil_image, config=self.tesseract_config_level)
                
                # Debug output
                if text.strip():
                    print(f"OCR Method {i+1} extracted: '{text.strip()}'")
                
                # Clean and extract numbers
                numbers = re.findall(r'\d+', text)
                if numbers:
                    # Level must be between 1 and 55
                    # Use valid range from class constants
                    min_level, max_level = self.valid_level_range
                    valid_numbers = [int(n) for n in numbers if min_level <= int(n) <= max_level]
                    if valid_numbers:
                        # Prefer numbers closer to the middle of the range (more likely to be correct)
                        # But also consider all valid numbers
                        for num in sorted(valid_numbers, key=lambda x: abs(x - (min_level + max_level) // 2)):
                            results.append(num)
            except Exception as e:
                print(f"Error in OCR method {i+1}: {e}")
        
        # Return the most common result, or the largest if no duplicates
        if results:
            # Count occurrences
            from collections import Counter
            counts = Counter(results)
            # Return the most common, or largest if tie
            most_common = counts.most_common(1)[0][0]
            print(f"Detected level: {most_common} (from {len(results)} attempts)")
            return most_common
        
        print("No level number found in any OCR method")
        return None
    
    def _correct_ocr_errors(self, text: str) -> str:
        """
        Correct common OCR errors, especially for 'prestige' text.
        Handles cases like 'prestice' -> 'prestige' where G is misread as C.
        
        Args:
            text: Raw OCR text
            
        Returns:
            Corrected text
        """
        if not text:
            return text
        
        # Direct replacement for common "prestige" misreadings
        # G is often misread as C, O, 0, 6, etc.
        corrections = {
            'prestice': 'prestige',
            'Prestice': 'Prestige',
            'PRESTICE': 'PRESTIGE',
            'prest0e': 'prestige',
            'Prest0e': 'Prestige',
            'prestoe': 'prestige',
            'Prestoe': 'Prestige',
            'prest6e': 'prestige',
            'Prest6e': 'Prestige',
        }
        
        # Apply direct replacements
        for wrong, correct in corrections.items():
            if wrong in text:
                text = text.replace(wrong, correct)
        
        # Pattern-based correction for variations
        # Fix "prestXe" where X is a misread G (c, 0, o, 6)
        text = re.sub(r'prest([c0o6])e', r'prest\1ge', text, flags=re.IGNORECASE)
        # If that created something weird, fix it
        text = re.sub(r'prest([c0o6])ge', 'prestige', text, flags=re.IGNORECASE)
        
        # Fix words that start with "prest" and have a misread character in position 6
        words = text.split()
        corrected_words = []
        for word in words:
            word_lower = word.lower()
            # If word looks like "prestige" with errors (starts with "prest" and is 7-9 chars)
            if word_lower.startswith('prest') and 7 <= len(word_lower) <= 9:
                # Check if character at position 5 or 6 might be a misread G
                if len(word_lower) >= 6:
                    char_at_5 = word_lower[5] if len(word_lower) > 5 else ''
                    char_at_6 = word_lower[6] if len(word_lower) > 6 else ''
                    # If we see c, 0, o, 6 in the G position, replace with g
                    if char_at_5 in 'c0o6' and char_at_6 == 'e':
                        # Replace the misread character with 'g'
                        if word[5].isupper():
                            word = word[:5] + 'G' + word[6:]
                        else:
                            word = word[:5] + 'g' + word[6:]
            corrected_words.append(word)
        
        return ' '.join(corrected_words)
    
    def _extract_numbers_with_bounding_boxes(self, image: np.ndarray, prestige_text_bbox: Optional[Tuple[int, int, int, int]] = None) -> List[Tuple[int, Tuple[int, int, int, int]]]:
        """
        Extract numbers from image using Tesseract's word-level data.
        Returns numbers with their bounding boxes for spatial matching.
        
        Args:
            image: Preprocessed image
            prestige_text_bbox: Optional bounding box of "prestige" text (x, y, w, h)
            
        Returns:
            List of (number, bbox) tuples where bbox is (x, y, w, h)
        """
        if not self.tesseract_available:
            return []
        
        numbers_found = []
        
        try:
            # Use PSM 6 (uniform block) to get all text with bounding boxes
            data = pytesseract.image_to_data(image, config=r'--oem 3 --psm 6', output_type=pytesseract.Output.DICT)
            
            # Extract all detected text with bounding boxes
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i].strip()
                conf = int(data['conf'][i])
                
                # Only consider high-confidence detections
                if conf > 30 and text:
                    # Check if this is a number
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        x = data['left'][i]
                        y = data['top'][i]
                        w = data['width'][i]
                        h = data['height'][i]
                        
                        for num_str in numbers:
                            num = int(num_str)
                            min_prestige, max_prestige = self.valid_prestige_range
                            if min_prestige <= num <= max_prestige:
                                numbers_found.append((num, (x, y, w, h)))
                                
                                # If we have prestige text bbox, check if number is nearby
                                if prestige_text_bbox:
                                    px, py, pw, ph = prestige_text_bbox
                                    # Check if number is to the right of prestige text (within reasonable distance)
                                    if (x >= px + pw - 10 and x <= px + pw + 100 and 
                                        abs(y - py) < max(h, ph) * 1.5):
                                        # This number is likely the prestige number
                                        return [(num, (x, y, w, h))]
        
        except Exception as e:
            print(f"Error extracting numbers with bounding boxes: {e}")
        
        return numbers_found
    
    def _extract_text_easyocr(self, image: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        """
        Extract text using EasyOCR (better for unusual fonts).
        
        Args:
            image: Preprocessed image
            
        Returns:
            List of (text, confidence, bbox) tuples where bbox is (x, y, w, h)
        """
        if not self.easyocr_available or self.easyocr_reader is None:
            return []
        
        try:
            # EasyOCR expects BGR format
            if len(image.shape) == 2:
                image_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            else:
                image_bgr = image
            
            # Run EasyOCR
            results = self.easyocr_reader.readtext(image_bgr)
            
            extracted = []
            for (bbox, text, confidence) in results:
                # bbox is list of 4 points [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                # Convert to (x, y, w, h) format
                x_coords = [point[0] for point in bbox]
                y_coords = [point[1] for point in bbox]
                x = int(min(x_coords))
                y = int(min(y_coords))
                w = int(max(x_coords) - x)
                h = int(max(y_coords) - y)
                
                extracted.append((text, confidence, (x, y, w, h)))
            
            return extracted
        
        except Exception as e:
            print(f"Error in EasyOCR extraction: {e}")
            return []
    
    def _is_likely_prestige(self, text: str) -> bool:
        """
        Check if text is likely "prestige" even with OCR errors.
        Uses simple character matching - if most characters match, consider it prestige.
        
        Args:
            text: OCR text to check
            
        Returns:
            True if text is likely "prestige"
        """
        if not text:
            return False
        
        text_lower = text.lower().strip()
        
        # Remove numbers and extra whitespace for comparison
        text_clean = re.sub(r'\d+', '', text_lower).strip()
        
        # Direct check for common misreadings of "prestige"
        # G can be misread as: c, 0, o, 6, etc.
        prestige_patterns = [
            r'prest[ic0o6]ge',    # prestige with G misread (prestcge, prest0ge, etc.)
            r'prest[ic0o6]e',     # prestice, prest0e, prestoe, prest6e
            r'prest[ic0o6]',      # just "prest" followed by misread G
        ]
        
        for pattern in prestige_patterns:
            if re.search(pattern, text_clean):
                return True
        
        # Check if it starts with "prest" and has similar length to "prestige" (8 chars)
        if text_clean.startswith('prest'):
            # "prestige" is 8 characters, allow 7-9 for OCR errors
            if 7 <= len(text_clean) <= 9:
                # Count matching characters in the first 8 positions
                target = "prestige"
                matches = 0
                for i in range(min(8, len(text_clean), len(target))):
                    if text_clean[i] == target[i]:
                        matches += 1
                    # Also count if character at position 5-6 is a common G misread
                    elif i == 5 and text_clean[i] in 'c0o6':
                        matches += 1  # Count as match since G is often misread
                
                # If at least 6 out of 8 characters match, consider it prestige
                if matches >= 6:
                    return True
        
        return False
    
    def extract_prestige_from_progression_screen(self, frame: np.ndarray, region: Tuple[int, int, int, int]) -> Tuple[Optional[int], str]:
        """
        Extract prestige from the progression screen.
        Looks for "Prestige X" text right above the level number.
        If "Prestige" is found, extracts the number after it.
        If "Prestige" is not found, returns 0.
        
        Args:
            frame: Original frame
            region: Region containing the progression screen (from template match)
            
        Returns:
            Tuple of (prestige number, raw OCR text)
            Prestige number (0 if no prestige found, 1+ if prestige exists), or None
            Raw OCR text for debugging
        """
        if not self.tesseract_available or frame is None or region is None:
            return None, ""
        
        x, y, w, h = region
        
        # Use configuration to determine prestige region (percentages relative to template)
        # This allows precise control via template_config.json
        prestige_region_x = x + int(w * self.prestige_region_config['x_percent'])
        prestige_region_y = y + int(h * self.prestige_region_config['y_percent'])
        prestige_region_w = int(w * self.prestige_region_config['width_percent'])
        prestige_region_h = int(h * self.prestige_region_config['height_percent'])
        
        # Ensure we don't go out of bounds
        prestige_region_x = max(0, prestige_region_x)
        prestige_region_y = max(0, prestige_region_y)
        prestige_region_w = min(frame.shape[1] - prestige_region_x, prestige_region_w)
        prestige_region_h = min(frame.shape[0] - prestige_region_y, prestige_region_h)
        
        # Make sure we have a valid region
        if prestige_region_h <= 0 or prestige_region_w <= 0:
            print("Prestige region is invalid")
            return 0, ""  # Default to 0 if we can't check
        
        prestige_roi = frame[prestige_region_y:prestige_region_y+prestige_region_h,
                            prestige_region_x:prestige_region_x+prestige_region_w]
        
        if prestige_roi.size == 0:
            print("Prestige ROI is empty")
            return 0, ""  # Default to 0
        
        # Preprocess for OCR - try multiple methods with enhanced preprocessing
        gray = cv2.cvtColor(prestige_roi, cv2.COLOR_BGR2GRAY)
        all_ocr_text = []  # Collect all OCR attempts for debugging
        
        # Try EasyOCR first (better for unusual fonts)
        if self.easyocr_available:
            try:
                # Scale up for better recognition
                scale_factor = 4
                enlarged_gray = cv2.resize(gray,
                                          (prestige_region_w * scale_factor, prestige_region_h * scale_factor),
                                          interpolation=cv2.INTER_CUBIC)
                
                # Apply sharpening
                kernel_sharpen = np.array([[-1,-1,-1],
                                          [-1, 9,-1],
                                          [-1,-1,-1]])
                enlarged_gray = cv2.filter2D(enlarged_gray, -1, kernel_sharpen)
                
                # Try EasyOCR
                easyocr_results = self._extract_text_easyocr(enlarged_gray)
                
                for text, confidence, bbox in easyocr_results:
                    if confidence > 0.5:  # Minimum confidence threshold
                        text_clean = self._correct_ocr_errors(text)
                        all_ocr_text.append(f"EasyOCR: {text_clean}")
                        print(f"EasyOCR extracted: '{text_clean}' (confidence: {confidence:.2f})")
                        
                        # Check if this is prestige text
                        is_prestige = self._is_likely_prestige(text_clean)
                        text_upper = text_clean.upper()
                        
                        if is_prestige or 'PRESTIGE' in text_upper:
                            # First, check if the number is in the same text (e.g., "PRESTIGE 1")
                            numbers_in_text = re.findall(r'\d+', text_clean)
                            if numbers_in_text:
                                num = int(numbers_in_text[0])
                                min_prestige, max_prestige = self.valid_prestige_range
                                if min_prestige <= num <= max_prestige:
                                    print(f"EasyOCR found Prestige: {num} (in same text)")
                                    return num, text_clean
                            
                            # Look for numbers in other EasyOCR results near this text
                            for other_text, other_conf, other_bbox in easyocr_results:
                                if other_conf > 0.5:
                                    # Check if this is a number near prestige text
                                    numbers = re.findall(r'\d+', other_text)
                                    if numbers:
                                        num = int(numbers[0])
                                        min_prestige, max_prestige = self.valid_prestige_range
                                        if min_prestige <= num <= max_prestige:
                                            # Check if number is spatially near prestige text
                                            px, py, pw, ph = bbox
                                            nx, ny, nw, nh = other_bbox
                                            # Number should be to the right of prestige text
                                            if (nx >= px + pw - 20 and nx <= px + pw + 150 and
                                                abs(ny - py) < max(ph, nh) * 2):
                                                print(f"EasyOCR found Prestige: {num} (in nearby text)")
                                                return num, text_clean
                            
                            # If prestige found but no nearby number, try extracting numbers with Tesseract
                            # Scale back down for Tesseract
                            numbers_with_bbox = self._extract_numbers_with_bounding_boxes(
                                enlarged_gray, prestige_text_bbox=bbox
                            )
                            if numbers_with_bbox:
                                prestige_num, _ = numbers_with_bbox[0]
                                print(f"EasyOCR found Prestige (with Tesseract number): {prestige_num}")
                                return prestige_num, text_clean
                            
                            # Just prestige word found, no number
                            print("EasyOCR found 'Prestige' but no number - defaulting to 0")
                            return 0, text_clean
            except Exception as e:
                print(f"EasyOCR error: {e}")
        
        # Enhanced preprocessing methods for Tesseract
        processed_images = []
        
        # Method 1: Denoise + Adaptive threshold
        denoised1 = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        thresh1 = cv2.adaptiveThreshold(
            denoised1, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        if np.mean(thresh1) < 128:
            thresh1 = cv2.bitwise_not(thresh1)
        processed_images.append(('adaptive_denoised', thresh1))
        
        # Method 2: High contrast + sharpening
        _, thresh2 = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        # Apply sharpening kernel
        kernel = np.array([[-1,-1,-1],
                           [-1, 9,-1],
                           [-1,-1,-1]])
        sharpened = cv2.filter2D(thresh2, -1, kernel)
        processed_images.append(('high_contrast_sharp', sharpened))
        
        # Method 3: Morphological operations to clean up text
        _, thresh3 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh3) < 128:
            thresh3 = cv2.bitwise_not(thresh3)
        # Morphological opening to remove noise
        kernel_morph = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        cleaned = cv2.morphologyEx(thresh3, cv2.MORPH_CLOSE, kernel_morph)
        processed_images.append(('morph_cleaned', cleaned))
        
        # Method 4: Bilateral filter for edge-preserving smoothing
        bilateral = cv2.bilateralFilter(gray, 9, 75, 75)
        _, thresh4 = cv2.threshold(bilateral, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh4) < 128:
            thresh4 = cv2.bitwise_not(thresh4)
        processed_images.append(('bilateral', thresh4))
        
        # Try all preprocessing methods
        for i, (method_name, processed) in enumerate(processed_images):
            try:
                # Scale up significantly for better OCR (larger text is easier to read)
                scale_factor = 4  # Increased from 3 to 4
                enlarged = cv2.resize(processed,
                                     (prestige_region_w * scale_factor, prestige_region_h * scale_factor),
                                     interpolation=cv2.INTER_CUBIC)
                
                # Additional sharpening after scaling
                kernel_sharpen = np.array([[-1,-1,-1],
                                          [-1, 9,-1],
                                          [-1,-1,-1]])
                enlarged = cv2.filter2D(enlarged, -1, kernel_sharpen)
                
                # Try multiple Tesseract configurations for better accuracy
                # Use PSM 7 (single text line) and 8 (single word) which work better for prestige text
                # Also try with character whitelist to focus on letters and numbers
                tesseract_configs = [
                    r'--oem 3 --psm 7',  # Single text line (best for "Prestige X")
                    r'--oem 3 --psm 8',  # Single word
                    r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ',  # Letters and numbers only
                    self.tesseract_config_text,  # Default
                ]
                
                best_text = ""
                best_confidence = 0
                
                for tesseract_config in tesseract_configs:
                    pil_image = Image.fromarray(enlarged)
                    text = pytesseract.image_to_string(pil_image, config=tesseract_config)
                    
                    # Try to get confidence score if available
                    try:
                        data = pytesseract.image_to_data(pil_image, config=tesseract_config, output_type=pytesseract.Output.DICT)
                        confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                        if avg_confidence > best_confidence:
                            best_confidence = avg_confidence
                            best_text = text
                    except:
                        # If confidence not available, just use the text
                        if not best_text:
                            best_text = text
                
                text = best_text.strip()
                
                # Apply character correction for common OCR errors
                text = self._correct_ocr_errors(text)
                
                # Collect OCR text for debugging
                if text.strip():
                    all_ocr_text.append(text.strip())
                    print(f"Prestige OCR Method {i+1} ({method_name}) extracted: '{text.strip()}'")
                
                text_upper = text.upper()
                
                # Check if text is likely "prestige" (handles OCR errors like "prestice")
                is_prestige = self._is_likely_prestige(text)
                
                # Look for "Prestige" followed by a number (exact match)
                prestige_pattern = re.compile(r'prestige\s*(\d+)', re.IGNORECASE)
                match = prestige_pattern.search(text)
                
                if match:
                    prestige_num = int(match.group(1))
                    min_prestige, max_prestige = self.valid_prestige_range
                    if min_prestige <= prestige_num <= max_prestige:
                        print(f"Found Prestige: {prestige_num}")
                        return prestige_num, text.strip()
                
                # If text is likely prestige (even with OCR errors), try to extract number
                if is_prestige or 'PRESTIGE' in text_upper:
                    # Try to find any number in the text (could be before or after "prestige")
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        prestige_num = int(numbers[0])
                        min_prestige, max_prestige = self.valid_prestige_range
                        if min_prestige <= prestige_num <= max_prestige:
                            print(f"Found Prestige (likely match, near number): {prestige_num}")
                            return prestige_num, text.strip()
                    
                    # If no number in text, try using bounding boxes to find numbers nearby
                    try:
                        # Get bounding box of prestige text from Tesseract data
                        data = pytesseract.image_to_data(enlarged, config=r'--oem 3 --psm 7', output_type=pytesseract.Output.DICT)
                        prestige_bbox = None
                        
                        # Find the bounding box of the prestige text
                        n_boxes = len(data['text'])
                        for i in range(n_boxes):
                            detected_text = data['text'][i].strip()
                            if detected_text and self._is_likely_prestige(detected_text):
                                prestige_bbox = (
                                    data['left'][i],
                                    data['top'][i],
                                    data['width'][i],
                                    data['height'][i]
                                )
                                break
                        
                        # Try to extract numbers using bounding boxes
                        if prestige_bbox:
                            numbers_with_bbox = self._extract_numbers_with_bounding_boxes(
                                enlarged, prestige_text_bbox=prestige_bbox
                            )
                            if numbers_with_bbox:
                                prestige_num, _ = numbers_with_bbox[0]
                                print(f"Found Prestige (using bounding boxes): {prestige_num}")
                                return prestige_num, text.strip()
                    except Exception as e:
                        print(f"Error extracting numbers with bounding boxes: {e}")
                    
                    # If "Prestige" found but no number, might be prestige 0 or error
                    print("Found 'Prestige' (or likely match) but no number - defaulting to 0")
                    return 0, text.strip()
                    
            except Exception as e:
                print(f"Error in prestige OCR method {i+1}: {e}")
        
        # If "Prestige" is not found in the text, return 0
        combined_text = " | ".join(all_ocr_text) if all_ocr_text else ""
        print(f"'Prestige' not found in text - defaulting to 0. OCR extracted: '{combined_text}'")
        return 0, combined_text
    
    def detect_progression_text(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the "PROGRESSION" text on screen using OCR.
        This is more reliable than template matching.
        
        Args:
            frame: Original frame from stream
            
        Returns:
            Region (x, y, width, height) where "PROGRESSION" text was found, or None
        """
        if frame is None or not self.tesseract_available:
            return None
        
        frame_h, frame_w = frame.shape[:2]
        
        # Search in the middle third of screen (where progression screen appears)
        search_x = int(frame_w * self.progression_region_config['x_percent'])
        search_y = int(frame_h * self.progression_region_config['y_percent'])
        search_w = int(frame_w * self.progression_region_config['width_percent'])
        search_h = int(frame_h * self.progression_region_config['height_percent'])
        
        # Ensure bounds
        search_x = max(0, search_x)
        search_y = max(0, search_y)
        search_w = min(frame_w - search_x, search_w)
        search_h = min(frame_h - search_y, search_h)
        
        # Extract search region
        search_roi = frame[search_y:search_y+search_h, search_x:search_x+search_w]
        
        if search_roi.size == 0:
            return None
        
        # Preprocess for OCR
        gray = cv2.cvtColor(search_roi, cv2.COLOR_BGR2GRAY)
        
        # Try multiple preprocessing methods
        for method in ['adaptive', 'threshold', 'high_contrast']:
            try:
                if method == 'adaptive':
                    thresh = cv2.adaptiveThreshold(
                        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY, 11, 2
                    )
                    if np.mean(thresh) < 128:
                        thresh = cv2.bitwise_not(thresh)
                elif method == 'threshold':
                    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    if np.mean(thresh) < 128:
                        thresh = cv2.bitwise_not(thresh)
                else:  # high_contrast
                    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                
                # Scale up for better OCR
                scale_factor = 2
                enlarged = cv2.resize(thresh,
                                     (search_w * scale_factor, search_h * scale_factor),
                                     interpolation=cv2.INTER_CUBIC)
                
                # Extract text
                pil_image = Image.fromarray(enlarged)
                text = pytesseract.image_to_string(pil_image, config=self.tesseract_config_text)
                
                # Check if "PROGRESSION" is in the text
                if 'PROGRESSION' in text.upper():
                    print(f"Found 'PROGRESSION' text in search region")
                    # Return the search region as the progression screen region
                    # We'll use this as the anchor point for level/prestige detection
                    return (search_x, search_y, search_w, search_h)
                    
            except Exception as e:
                print(f"Error in progression text detection ({method}): {e}")
                continue
        
        return None
    
    def detect_multiple_regions(self, frame: np.ndarray) -> Tuple[Optional[Dict[str, int]], list]:
        """
        Detect level and prestige from the progression screen by finding "PROGRESSION" text.
        
        Args:
            frame: Frame from stream capture
            
        Returns:
            Tuple of (detection result dict, list of regions checked)
            Result dict has 'level' and 'prestige' keys, or None if not detected
        """
        if frame is None:
            return None, []

        # Try to detect "PROGRESSION" text on screen
        progression_region = self.detect_progression_text(frame)

        if progression_region is None:
            # No progression screen detected
            return None, []

        # Extract level and prestige from progression screen
        # Use the progression region as the anchor point
        level = self.extract_level_from_progression_screen(frame, progression_region)
        prestige_result = self.extract_prestige_from_progression_screen(frame, progression_region)
        
        # Handle new return format (prestige, ocr_text)
        if isinstance(prestige_result, tuple):
            prestige, prestige_ocr_text = prestige_result
        else:
            prestige = prestige_result
            prestige_ocr_text = ""

        # Return regions for visualization
        regions = [progression_region]

        if level is not None:
            # Validate and clamp values to valid ranges using class constants
            min_level, max_level = self.valid_level_range
            min_prestige, max_prestige = self.valid_prestige_range
            
            validated_level = max(min_level, min(max_level, level)) if level is not None else None
            validated_prestige = max(min_prestige, min(max_prestige, prestige)) if prestige is not None else 0
            
            # Only return result if level is in valid range
            if validated_level is not None and min_level <= validated_level <= max_level:
                result = {
                    'level': validated_level,
                    'prestige': validated_prestige,
                    'prestige_ocr_text': prestige_ocr_text  # Debug: raw OCR text
                }
                return result, regions

        return None, regions
    
    def draw_detection_regions(self, frame: np.ndarray, regions: list, 
                               detected_region: Optional[Tuple[int, int, int, int]] = None,
                               level: Optional[int] = None,
                               prestige: Optional[int] = None) -> np.ndarray:
        """
        Draw boxes around detection regions on the frame.
        If progression screen is detected, also draw level and prestige sub-regions.
        
        Args:
            frame: Original frame
            regions: List of regions checked (x, y, width, height)
            detected_region: The region where level/prestige was detected (optional)
            level: Detected level number (optional)
            prestige: Detected prestige number (optional)
            
        Returns:
            Frame with detection boxes drawn
        """
        if frame is None:
            return frame
        
        annotated_frame = frame.copy()
        
        if not regions:
            return annotated_frame
        
        # Track which region is the progression screen for drawing level/prestige boxes
        progression_region = None
        if detected_region is not None and len(detected_region) == 4:
            # Find the matching region
            for region in regions:
                if len(region) == 4 and tuple(region) == tuple(detected_region):
                    progression_region = region
                    break
        
        # If no detected region matches, use first region if we have level/prestige values
        # This ensures saved annotated frames always show all annotation boxes
        if progression_region is None and (level is not None or prestige is not None) and len(regions) > 0:
            progression_region = regions[0]
        
        for i, region in enumerate(regions):
            if len(region) != 4:
                continue
                
            x, y, w, h = region
            
            # Check if this is the detected region (compare as tuples)
            is_detected = (detected_region is not None and 
                          len(detected_region) == 4 and
                          tuple(region) == tuple(detected_region))
            
            # Also check if this is the progression region we identified
            is_progression = (progression_region is not None and 
                            tuple(region) == tuple(progression_region))
            
            # Use green for detected region, blue for progression screen, red for others
            if is_detected:
                color = (0, 255, 0)  # Green for detected
                thickness = 3
                label = "PROGRESSION SCREEN"
            else:
                color = (255, 165, 0)  # Orange for search regions
                thickness = 2
                label = f"Search Region {i+1}"
            
            # Draw rectangle
            cv2.rectangle(annotated_frame, (x, y), (x + w, y + h), color, thickness)
            
            # Draw label
            if y > 20:  # Only draw label if there's room above
                cv2.putText(annotated_frame, label, (x, y - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            else:
                cv2.putText(annotated_frame, label, (x, y + 20), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # If this is the progression screen and we detected level/prestige, draw sub-regions
            # Always draw level/prestige boxes on the progression region if we have values
            if is_progression and (level is not None or prestige is not None):
                # Draw level extraction region using config
                level_region_x = x + int(w * self.level_region_config['x_percent'])
                level_region_y = y + int(h * self.level_region_config['y_percent'])
                level_region_w = int(w * self.level_region_config['width_percent'])
                level_region_h = int(h * self.level_region_config['height_percent'])
                
                cv2.rectangle(annotated_frame, 
                            (level_region_x, level_region_y),
                            (level_region_x + level_region_w, level_region_y + level_region_h),
                            (0, 255, 255), 2)  # Cyan for level region
                level_label = f"LEVEL: {level}" if level is not None else "LEVEL: ?"
                cv2.putText(annotated_frame, level_label, 
                          (level_region_x, level_region_y - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                
                # Draw prestige extraction region using config
                prestige_region_x = x + int(w * self.prestige_region_config['x_percent'])
                prestige_region_y = y + int(h * self.prestige_region_config['y_percent'])
                prestige_region_w = int(w * self.prestige_region_config['width_percent'])
                prestige_region_h = int(h * self.prestige_region_config['height_percent'])
                
                cv2.rectangle(annotated_frame,
                            (prestige_region_x, prestige_region_y),
                            (prestige_region_x + prestige_region_w, prestige_region_y + prestige_region_h),
                            (255, 0, 255), 2)  # Magenta for prestige region
                prestige_label = f"PRESTIGE: {prestige}" if prestige is not None else "PRESTIGE: ?"
                cv2.putText(annotated_frame, prestige_label,
                          (prestige_region_x, prestige_region_y - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
        
        return annotated_frame

