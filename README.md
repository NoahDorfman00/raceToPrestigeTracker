# StreamWatcher - Call of Duty Level/Prestige Detector

A web application that monitors Twitch streams and uses computer vision to detect and display the player's level and prestige in Call of Duty.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install Tesseract OCR:
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
   - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki

3. Install streamlink (if not already installed):
   ```bash
   pip install streamlink
   ```

4. Add template image:
   - Place a cropped screenshot of the progression screen UI in `template_images/progression_template.png`
   - The template should be cropped to show just the circular progression UI element
   - Include the level number, rank text, and star icon in the template

5. Run the application:
```bash
python app.py
```

6. Open your browser to `http://localhost:5001`

## Troubleshooting

### Tesseract OCR Not Found

If you see an error about Tesseract not being installed:

- **macOS**: Run `brew install tesseract`
- **Linux**: Run `sudo apt-get install tesseract-ocr`
- **Windows**: Download and install from https://github.com/UB-Mannheim/tesseract/wiki

After installing, verify it's in your PATH by running:
```bash
tesseract --version
```

The application will still run and display the stream, but detection will not work until Tesseract is installed.

## Usage

Enter a Twitch stream URL or username in the web interface to start monitoring.

## Configuration

You can fine-tune where OpenCV looks for the level and prestige text by editing `template_config.json`. This file allows you to specify exact regions as percentages of the template image.

### Configuring Regions

Edit `template_config.json` to adjust the regions:

```json
{
    "level_region": {
        "x_percent": 0.3,      // X position (30% from left)
        "y_percent": 0.45,     // Y position (45% from top)
        "width_percent": 0.4,   // Width (40% of template width)
        "height_percent": 0.2   // Height (20% of template height)
    },
    "prestige_region": {
        "x_percent": 0.3,      // X position (30% from left)
        "y_percent": 0.3,      // Y position (30% from top)
        "width_percent": 0.5,   // Width (50% of template width)
        "height_percent": 0.15  // Height (15% of template height)
    }
}
```

### How to Find the Right Values

1. Use the **Test Mode** page (`/test`) to upload a screenshot
2. Check the debug ROI images to see what regions are being extracted
3. Adjust the percentages in `template_config.json` until the cyan and magenta boxes align perfectly with the level number and prestige text
4. Restart the app to load the new configuration

### Example

If the level number appears at 35% from left and 50% from top in your template:
- Set `x_percent: 0.35` and `y_percent: 0.50` in `level_region`

