# Commute ETA

A lightweight macOS menu bar app that shows live drive time to saved destinations using Google Maps traffic data. Glance at your menu bar, know when to leave.

![example](https://img.shields.io/badge/menu_bar-🏠_1_hr_42_min_🟢-333?style=flat-square)

## What it does

- Sits in your macOS menu bar showing real-time drive time with traffic
- Color-coded severity: 🟢 clear, 🟡 moderate, 🟠 heavy, 🔴 severe
- Shows alternate routes in the dropdown
- Click a destination to make it the title-bar display
- "Open in Google Maps" to see the full route
- Polls every 5 minutes (configurable)

## Setup

### 1. Get a Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable the **Directions API**: [Direct link](https://console.cloud.google.com/apis/library/directions-backend.googleapis.com)
4. Go to **Credentials** → **Create Credentials** → **API Key**
5. (Recommended) Restrict the key to **Directions API** only

**Cost:** Google gives you $200/month free credit. At one poll every 5 minutes, that's ~8,640 requests/month. Directions API costs $0.005/request = ~$43/month. Well within the free tier.

### 2. Install Dependencies

```bash
pip3 install rumps requests
```

### 3. Configure

```bash
# First run creates ~/.commute_eta/config.json with defaults
python3 commute_eta.py

# Or copy the example and edit
mkdir -p ~/.commute_eta
cp config.example.json ~/.commute_eta/config.json
```

Edit `~/.commute_eta/config.json`:

```json
{
  "api_key": "AIza...",
  "poll_interval_seconds": 300,
  "show_route_index": 0,
  "destinations": [
    {
      "name": "Home",
      "origin": "Burbank, CA",
      "destination": "Los Angeles, CA",
      "icon": "🏠"
    },
    {
      "name": "Office",
      "origin": "Los Angeles, CA",
      "destination": "Burbank, CA",
      "icon": "🏢"
    }
  ]
}
```

You can add as many destinations as you want. Use full street addresses for best accuracy.

### 4. Run

```bash
python3 commute_eta.py
```

### 5. (Optional) Auto-start at Login

Create a Launch Agent:

```bash
cat > ~/Library/LaunchAgents/com.commute-eta.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.commute-eta</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/commute_eta.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/commute_eta.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/commute_eta.stderr.log</string>
</dict>
</plist>
EOF
```

Update the python3 path (`which python3`) and the script path, then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.commute-eta.plist
```

## Config Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `api_key` | string | — | Your Google Maps API key |
| `poll_interval_seconds` | int | 300 | How often to refresh (seconds) |
| `show_route_index` | int | 0 | Which destination to show in menu bar |
| `destinations` | array | — | List of destination objects |

### Destination Object

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Display name |
| `origin` | string | Starting address |
| `destination` | string | Ending address |
| `icon` | string | Emoji shown in menu bar and dropdown |

## Log

Activity is logged to `~/.commute_eta/commute_eta.log`.
