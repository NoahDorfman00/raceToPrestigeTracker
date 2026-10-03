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

3. Install streamlink (included in `requirements.txt`). If it is not on `PATH` or in the
   active virtualenv, set `STREAMLINK_PATH` to the executable.

4. Configure environment variables (copy `env.example` to `.env`):
   - `AUTHORIZED_ADMIN_EMAILS` (required for the admin panel): comma-separated list of
     Google account emails allowed to use admin endpoints. If unset, all admin requests are rejected.
   - `FIREBASE_STORAGE_BUCKET` (required for uploads): bucket that `streams_data.json`
     and annotated frames are published to. If unset, uploads are disabled.
   - Firebase credentials: add `firebase-service-account.json` to the project root, or set
     `FIREBASE_SERVICE_ACCOUNT_JSON`.

5. Run the application:
```bash
python app.py
```

6. Open your browser to `http://localhost:5001`

## Usage

1. **Public Leaderboard**: Visit the homepage to view the real-time leaderboard of all monitored streamers
2. **Admin Panel**: Access `/admin` to add/remove streams (requires Firebase authentication)
3. **Test Mode**: Use `/test` to test detection on screenshots and configure detection regions

## How detection works

No template image is needed. Each frame is searched (within `progression_region` of
`template_config.json`) for the "PROGRESSION" heading using OCR. When it's found, the level
and prestige are read from regions positioned relative to that heading.

A reading lower than a streamer's stored progress is treated as a likely misread and ignored.
It is only accepted if lower readings keep arriving, with no reading at or above the stored value
in between, for at least `REGRESSION_CONFIRM_COUNT` detections (default 5) and
`REGRESSION_CONFIRM_SECONDS` (default 600).

## Configuration

Detection regions can be fine-tuned in `template_config.json` or via the Test Mode interface
(saving changes requires an admin token). The configuration specifies where to search for the
"PROGRESSION" heading and where to read level and prestige text relative to it.

## Published data

`streams_data.json` (uploaded to Firebase Storage) has these per-stream fields:
- `is_active`: the stream is being tracked (on the leaderboard). This does not mean it's live.
- `is_live`: the stream was live on Twitch at the most recent live check (runs every 60 seconds).
  `live_changed_at` records when this value last changed.

