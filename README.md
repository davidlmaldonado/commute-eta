# Commute ETA

A lightweight macOS menu bar app that shows live drive time to saved destinations using Google Maps traffic data. Glance at your menu bar, know when to leave.

## What it does

- Sits in your macOS menu bar showing real-time drive time with traffic
- Color-coded severity: 🟢 clear, 🟡 moderate, 🟠 heavy, 🔴 severe
- Shows alternate routes in the dropdown
- Click a destination to make it the title-bar display
- **Schedule-aware** — only polls during your commute windows, sleeps the rest of the time (😴)
- "Refresh Now" forces a check anytime, even outside active hours
- "Open in Google Maps" to see the full route
- Configurable poll interval (default: every 5 minutes)

## Setup

### 1. Get a Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable the **Directions API**: [Direct link](https://console.cloud.google.com/apis/library/directions-backend.googleapis.com)
4. Go to **Credentials** → **Create Credentials** → **API Key**
5. (Recommended) Restrict the key to **Directions API** only

**Cost:** Google gives you $200/month free credit. With active hours set to typical commute windows (6 hrs/day, weekdays only), you'll use roughly 1,500 requests/month — about $8, well within the free tier.

### 2. Install Dependencies

```bash
pip3 install rumps requests
```

### 3. Configure

The app stores its config at `~/.commute_eta/config.json`.

**First run** — this generates the default config file and exits:

```bash
cd ~/Documents/GitHub/commute-eta   # or wherever you cloned the repo
python3 commute_eta.py
```

You'll see a menu bar icon with a warning. Quit it (click icon → Quit), then open the config:

```bash
open ~/.commute_eta/config.json
```

Edit it with your API key and real addresses:

```json
{
  "api_key": "AIza...",
  "poll_interval_seconds": 300,
  "show_route_index": 0,
  "active_hours": [
    {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "06:00", "end": "09:00"},
    {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "15:00", "end": "19:00"}
  ],
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

Use full street addresses for best route accuracy.

### 4. Run

Save the config, then run again from the repo folder:

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
| `active_hours` | array | — | Time windows when polling is active |
| `destinations` | array | — | List of destination objects |

### Active Hours

Each entry in `active_hours` defines a time window:

| Key | Type | Description |
|-----|------|-------------|
| `days` | array | Day abbreviations: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun` |
| `start` | string | Start time in 24hr format, e.g. `"06:00"` |
| `end` | string | End time in 24hr format, e.g. `"09:00"` |

Outside active hours, the app shows 😴 in the menu bar and makes zero API calls. "Refresh Now" still works anytime.

To disable scheduling and poll 24/7, set `"active_hours": []`.

### Destination Object

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Display name |
| `origin` | string | Starting address |
| `destination` | string | Ending address |
| `icon` | string | Emoji shown in menu bar and dropdown |

## Log

Activity is logged to `~/.commute_eta/commute_eta.log`.
