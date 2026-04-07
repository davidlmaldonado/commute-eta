# Commute ETA

A lightweight macOS menu bar app that shows live drive time to saved destinations using Google Maps traffic data. Glance at your menu bar, know when to leave.

## What it does

- Sits in your macOS menu bar showing real-time drive time with traffic
- Color-coded severity: 🟢 clear, 🟡 moderate, 🟠 heavy, 🔴 severe
- **Trend arrows** — see if traffic is getting better (↓), worse (↑), or steady (→)
- **Leave-by time** — tells you when to leave to arrive by a target time
- **Traffic spike alerts** — macOS notification when drive time jumps significantly
- **Schedule-aware** — only polls during your commute windows, sleeps the rest of the time (😴)
- **Auto-switches** — shows the right destination based on time of day (morning = office, afternoon = home)
- Shows alternate routes in the dropdown
- Pause/resume toggle — stop polling without quitting
- "Refresh Now" forces a check anytime
- "Open in Google Maps" to see the full route
- Only polls the active destination — saves API calls

## Setup

### 1. Clone the Repo

```bash
git clone https://github.com/davidlmaldonado/commute-eta.git
cd commute-eta
```

Or click the green **"<> Code"** button on GitHub and select **"Open with GitHub Desktop"**.

### 2. Install Dependencies

```bash
pip3 install rumps requests
```

### 3. Get a Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable the **Directions API**: [Direct link](https://console.cloud.google.com/apis/library/directions-backend.googleapis.com)
4. Go to **Credentials** → **Create Credentials** → **API Key**
5. (Recommended) Restrict the key to **Directions API** only

**Cost:** Google gives you $200/month free credit. With active hours set to typical commute windows (6 hrs/day, weekdays only) and single-destination polling, you'll use roughly 720 requests/month — about $4, well within the free tier.

### 4. Configure

The app stores its config at `~/.commute_eta/config.json` (not in the repo folder).

**First run** — this generates the default config file:

```bash
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
    {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "06:00", "end": "09:00", "show_destination": 1},
    {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "15:00", "end": "19:00", "show_destination": 0}
  ],
  "notifications": {
    "enabled": true,
    "spike_threshold_minutes": 15
  },
  "arrive_by": {
    "Morning Commute": "08:30",
    "Heading Home": "18:30"
  },
  "destinations": [
    {
      "name": "Heading Home",
      "origin": "Burbank, CA",
      "destination": "Los Angeles, CA",
      "icon": "🏠"
    },
    {
      "name": "Morning Commute",
      "origin": "Los Angeles, CA",
      "destination": "Burbank, CA",
      "icon": "🏢"
    }
  ]
}
```

Use full street addresses for best route accuracy.

### 5. Run

Save the config, then run again from the repo folder:

```bash
python3 commute_eta.py
```

### 6. (Optional) Auto-start at Login

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
Load it:
launchctl load ~/Library/LaunchAgents/com.commute-eta.plist

To reload after changes:
launchctl unload ~/Library/LaunchAgents/com.commute-eta.plist
launchctl load ~/Library/LaunchAgents/com.commute-eta.plist
```

## Config Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `api_key` | string | — | Your Google Maps API key |
| `poll_interval_seconds` | int | 300 | How often to refresh (seconds) |
| `show_route_index` | int | 0 | Which destination to show in menu bar |
| `active_hours` | array | — | Time windows when polling is active |
| `notifications` | object | — | Traffic spike notification settings |
| `arrive_by` | object | — | Target arrival times per destination |
| `destinations` | array | — | List of destination objects |

### Active Hours

Each entry in `active_hours` defines a time window:

| Key | Type | Description |
|-----|------|-------------|
| `days` | array | Day abbreviations: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun` |
| `start` | string | Start time in 24hr format, e.g. `"06:00"` |
| `end` | string | End time in 24hr format, e.g. `"09:00"` |
| `show_destination` | int | (Optional) Index of the destination to display during this window |

The `show_destination` field auto-switches which route is shown based on the time of day. For example, set `"show_destination": 1` on your morning window to show your commute to the office, and `"show_destination": 0` on your afternoon window to show your drive home. Only the active destination is polled, which also cuts API usage in half.

Outside active hours, the app shows 😴 in the menu bar and makes zero API calls. "Refresh Now" still works anytime.

To disable scheduling and poll 24/7, set `"active_hours": []`.

### Notifications

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | true | Send macOS notifications on traffic spikes |
| `spike_threshold_minutes` | int | 15 | Minimum increase (minutes) to trigger a notification |

When drive time jumps by more than the threshold between polls, you'll get a macOS notification like: "Traffic Spike — Heading Home — Drive time jumped to 2 hr 30 min (+18m)"

### Arrive By

Maps destination names to target arrival times in 24hr format:

```json
"arrive_by": {
    "Morning Commute": "08:30",
    "Heading Home": "18:30"
}
```

The dropdown will show a "leave by" time based on current traffic, e.g. "🕐 Leave by 4:48 PM to arrive by 18:30". If you're already past the leave-by time, it tells you you're cutting it close.

### Destination Object

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Display name (also used as the key in `arrive_by`) |
| `origin` | string | Starting address |
| `destination` | string | Ending address |
| `icon` | string | Emoji shown in menu bar and dropdown |

## Log

Activity is logged to `~/.commute_eta/commute_eta.log`.
