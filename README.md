# Call of Duty Black Ops 7: Race To Master Prestige

A real-time leaderboard tracking system that monitors Twitch streams for Call of Duty Black Ops 7 streamers racing to Master Prestige. The application uses computer vision and OCR to automatically detect and track each streamer's prestige and level progression.

## What is this project?

This project is a web application that:

- **Monitors Twitch streams** of Call of Duty Black Ops 7 players
- **Automatically detects** prestige and level using computer vision (OpenCV) and OCR (Tesseract/EasyOCR)
- **Tracks progression** in real-time as streamers play
- **Displays a leaderboard** ranking all monitored streamers by their progression
- **Saves detection frames** and data to Firebase Storage for persistence

Perfect for tracking community challenges or races to Master Prestige where multiple streamers are competing simultaneously.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install Tesseract OCR:
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
   - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki

3. Add template image:
   - Place a cropped screenshot of the progression screen UI in `template_images/progression_template.png`
   - The template should show the circular progression UI element with level number and prestige text

4. Configure Firebase (optional, for data persistence):
   - Add `firebase-service-account.json` to project root
   - Or set `FIREBASE_SERVICE_ACCOUNT_JSON` environment variable

5. Run the application:
```bash
python app.py
```

6. Open your browser to `http://localhost:5001`

## Usage

1. **Public Leaderboard**: Visit the homepage to view the real-time leaderboard of all monitored streamers
2. **Admin Panel**: Access `/admin` to add/remove streams (requires Firebase authentication)
3. **Test Mode**: Use `/test` to test detection on screenshots and configure detection regions

## Configuration

Detection regions can be fine-tuned in `template_config.json` or via the Test Mode interface. The configuration specifies where to look for level and prestige text relative to the progression UI element.

