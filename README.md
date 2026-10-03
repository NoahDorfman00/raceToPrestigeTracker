# The Race Board

A live leaderboard for the Call of Duty: Black Ops 7 race to Master
Prestige. It watches streamers' Twitch broadcasts, waits for them to open
the in-game **Progression** screen, reads their prestige and level off the
pixels with OpenCV and OCR, and ranks them at
[theraceboard.com](https://theraceboard.com/). Nobody has to type in a
score.

<p align="center">
  <img src="https://raw.githubusercontent.com/NoahDorfman00/raceToPrestigeTrackerFrontend/main/social.png" alt="The Race Board leaderboard: ranked streamers with prestige, level, live status and a Watch Stream button" width="640">
</p>

This repo is the backend: stream capture, detection, and publishing. The
public site is a single static page in
[raceToPrestigeTrackerFrontend](https://github.com/NoahDorfman00/raceToPrestigeTrackerFrontend).

## Why

Just for fun. Several streamers were racing to Master Prestige in Black Ops
7, and the only way to see who was ahead was to check in on each stream. I
wanted the standings without doing that, so The Race Board watches them for
me.

## How it works

```
Twitch ──streamlink──► OpenCV VideoCapture ──latest frame──► detector (every 2s)
                                                                 │
                                    "PROGRESSION" header found? ─┤ no → skip
                                                                 │ yes
                                         level ROI ──► Tesseract (digits, 3 binarizations, vote)
                                      prestige ROI ──► EasyOCR → Tesseract fallback
                                                                 │
                     streams_data.json + annotated frame ──► Firebase Storage ──► theraceboard.com
```

**1. Getting frames.** Each tracked channel gets its own capture thread.
[streamlink](https://streamlink.github.io/) resolves the channel to its
`best` HLS URL (`streamlink --stream-url <channel> best`, retried up to
three times), and that URL goes straight into `cv2.VideoCapture`. The
capture loop reads continuously but keeps only the newest frame (a
two-slot queue that drops the oldest), so a slow detector never builds a
backlog. Frames can optionally be downscaled with `FRAME_SCALE` to save
memory.

**2. Sampling.** A detection thread per stream pulls the latest frame and
runs detection at most once every **2 seconds**. Separately, a live-check
thread asks streamlink every **60 seconds** whether each channel is live
and starts or stops its capture accordingly, so an offline channel costs
one status check a minute. The server caps tracked streams at `MAX_STREAMS` (default 5).

**3. Is this the Progression screen?** Nearly every frame is gameplay,
not the menu that shows rank. The detector crops a search region (the
middle third of the frame horizontally, top ~70% vertically; see
`template_config.json`), binarizes it three ways (adaptive, Otsu, and a
fixed white-text threshold), upscales 2x, and runs Tesseract looking for
the word `PROGRESSION`. No word, no detection: the frame is thrown away.

**4. Reading the level.** If the header is found, its region becomes the
anchor and the level and prestige boxes are defined as percentages of it
(also in `template_config.json`). The level crop gets three binarizations,
a 4x upscale and a sharpening kernel, then Tesseract in single-word mode
with a digits-only whitelist. Only numbers inside the detector's valid range
count, and the most common answer across the three passes wins.

**5. Reading the prestige.** Harder, because it's stylized text
("PRESTIGE 3", or "PRESTIGE MASTER") rather than one big number:

- EasyOCR goes first (if enabled), keeping results above 0.5 confidence.
- A fuzzy matcher accepts OCR's favorite misreadings of "prestige"
  (`PRESTICE`, `PREST0E`, `PREST6E`, ...).
- The number is taken from the same text box, or from a separate box
  that sits to the right of the word, using bounding boxes from either OCR
  engine.
- "PRESTIGE MASTER" is stored as prestige **20**, a sentinel that sorts
  above everything else; the frontend displays it as "Prestige Master".
- If EasyOCR comes up empty, Tesseract tries four preprocessing variants
  times four page-segmentation configs and keeps the highest-confidence
  read.
- If nothing says "prestige", the player is treated as prestige 0.

**6. Sanity check.** A reading lower than a streamer's stored progress is
treated as a misread and ignored. It's only accepted if lower readings keep
arriving, with nothing at or above the stored value in between, for at least
`REGRESSION_CONFIRM_COUNT` detections (default 5) and
`REGRESSION_CONFIRM_SECONDS` (default 600). One bad frame can't knock anyone
down the board.

**7. Publishing.** A complete detection (header + valid level) writes an
annotated copy of the frame with the detection boxes drawn on it, plus a
small OCR log (the raw text that was read). Stream state lives in a plain
JSON file, `streams_data.json`, which is re-uploaded to Firebase Storage in
a background thread every time it's saved. The annotated frame is uploaded
to a fixed path, `annotated_frames/stream_<id>_annotated.jpg`, so each new
detection simply overwrites the last one.

**8. The frontend.** [theraceboard.com](https://theraceboard.com/) is one
static `index.html`, served by GitHub Pages from the frontend repo. It uses
the Firebase JS SDK to fetch
`streams_data.json` from Storage, ranks streamers client-side (prestige,
then level), uses `is_live` from the backend's 60-second live check for
the live dot and Watch Stream button, and shows each streamer's last annotated frame and OCR text
behind an info button, so anyone can check the robot's work. If the
browser hits a CORS error it retries through a public CORS proxy.

**Admin and debugging.** The Flask app also serves its own pages:

- `/admin`: add or remove channels, behind Google sign-in via Firebase
  Auth, with tokens verified server-side and checked against an email
  allowlist.
- `/test`: upload a screenshot or a short clip (it samples every 10th
  frame of the first 100) to see what the detector reads, and adjust the
  region percentages live.
- `/`: the backend's own leaderboard page, polling `/api/leaderboard`
  every 5 seconds.

## Stack

| Piece | What it does |
|-------|--------------|
| **Python / Flask** | API, admin and test pages, background threads |
| **streamlink** | Twitch channel → HLS URL, and "is this channel live?" |
| **OpenCV** | Frame capture, cropping, thresholding, annotation |
| **Tesseract** (pytesseract) | Header, level, and fallback prestige OCR |
| **EasyOCR** | Primary prestige OCR (optional; ~1–2 GB RAM) |
| **Firebase** | Storage for the published JSON and frames; Auth for the admin page |
| **HTML / CSS / JS** | The static public leaderboard (frontend repo) |

## Running it locally

You need Python 3.9+, Tesseract, and (optionally) a Firebase project.

```bash
# Tesseract
brew install tesseract              # macOS
sudo apt-get install tesseract-ocr  # Debian/Ubuntu

# Python deps (streamlink comes from requirements.txt)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Config
cp env.example .env                 # then fill it in

python app.py                       # http://localhost:5001
```

Run it as a single process. Stream monitoring, the live check and the JSON
store all live in one process, so multiple gunicorn workers would each start
their own monitors and overwrite each other's data.

On a Debian/Ubuntu or RHEL-family server, `sudo ./deploy.sh` installs the
system packages, creates the venv, and checks that Tesseract and streamlink
are reachable. [DEPLOYMENT.md](DEPLOYMENT.md) covers systemd and nginx.

Environment variables (all placeholders; see `env.example`):

| Variable | Purpose |
|----------|---------|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Service-account JSON for Admin SDK + Storage (or drop `firebase-service-account.json` in the project root) |
| `FIREBASE_STORAGE_BUCKET` | Bucket that receives `streams_data.json` and frames (uploads are disabled if unset) |
| `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID`, `FIREBASE_MESSAGING_SENDER_ID`, `FIREBASE_APP_ID`, `FIREBASE_MEASUREMENT_ID` | Client config served to the admin page for sign-in |
| `AUTHORIZED_ADMIN_EMAILS` | Comma-separated allowlist for `/admin` and saving detection config (all admin requests are rejected if unset) |
| `MAX_STREAMS` | Cap on tracked channels (default 5) |
| `DISABLE_EASYOCR` | `true` to run Tesseract-only and save ~1–2 GB RAM |
| `FRAME_SCALE` | Downscale captured frames (e.g. `0.75`) |
| `STREAMLINK_PATH` | Path to streamlink, if it isn't on `PATH` or in the venv |
| `REGRESSION_CONFIRM_COUNT`, `REGRESSION_CONFIRM_SECONDS` | How long a lower reading must persist before it's believed (defaults 5 and 600) |
| `PORT`, `FLASK_ENV` | Server port (default 5001) and dev/prod mode |

You need Firebase for most of this to be useful: adding channels and the
`/test` uploads both go through the admin login. Without it, detection
results still land in a local `streams_data.json` and `annotated_frames/`,
and any active channels already in `streams_data.json` are restored and
tracked on startup.

> The app still looks for an optional template image at
> `template_images/progression_template.png` and warns if it's missing. It's
> a leftover from an earlier template-matching approach (see below) and
> detection works without it.

**Frontend:** put your Firebase web config into `index.html`, allow
cross-origin reads on the bucket with
`gsutil cors set cors.json gs://<your-bucket>`, and serve the folder with
`python3 -m http.server 8000`.

## Known rough edges

- Detection regions are fixed percentages in `template_config.json`, so a
  different HUD layout or a stream overlay covering the menu can push the
  text out of the box.
- The board can't see you level up mid-match. It finds out when you open
  the Progression screen on stream.

## Lessons learned

1. **Find the word, not the picture.** Finding the Progression screen by
   OCRing its header turned out more reliable than template-matching the UI
   badge, and the multi-scale template matcher is still in
   `level_detector.py`, unused.
2. **OCR is a vote, not a read.** Every value goes through several
   binarizations, only answers in a valid range get a vote, and no single
   preprocessing pass is trusted on its own.
3. **Teach the code your OCR's typos.** OCR misreads the G in "PRESTIGE"
   (PRESTICE, PREST0E, PREST6E) often enough that part of the detector
   exists only to forgive it.
4. **A JSON file in a bucket is a fine database for one writer.** The
   backend is the only thing that writes, so the public site is a static
   page reading a file and needs no server of its own.
5. **Better OCR costs gigabytes.** EasyOCR handles the stylized prestige
   font better than Tesseract but takes 1–2 GB of RAM, which is why there's
   a switch to turn it off.

## Repo layout

```
app.py               Flask app: public/admin/test pages, REST API, startup restore
stream_capture.py    streamlink → OpenCV capture thread (latest-frame-only queue)
stream_manager.py    per-stream detection loops, 60s live checks, saving results
level_detector.py    the CV/OCR pipeline (Progression header, level, prestige)
database.py          streams_data.json store + leaderboard sort
firebase_storage.py  background uploads to Firebase Storage
template_config.json detection region percentages
templates/           index.html (leaderboard), admin.html, test.html
deploy.sh            Linux server setup;  DEPLOYMENT.md  systemd/nginx guide
build.sh, aptfile, runtime.txt   Render build config
```

Frontend repo:

```
index.html   the whole public site: fetch, rank, render
cors.json    Storage CORS policy
social.png   link-preview image
CNAME        theraceboard.com
```

## Credits

The heavy lifting is done by [streamlink](https://streamlink.github.io/),
[Tesseract](https://github.com/tesseract-ocr/tesseract),
[EasyOCR](https://github.com/JaidedAI/EasyOCR), and
[OpenCV](https://opencv.org/). Call of Duty and Black Ops are trademarks of
Activision; this is an unofficial fan project.
