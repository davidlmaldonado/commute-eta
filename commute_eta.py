#!/usr/bin/env python3
"""
Commute ETA — A macOS menu bar app that shows live drive time to saved destinations.
Uses Google Maps Directions API with real-time traffic data.

Requirements:
    pip install rumps requests

Setup:
    1. Get a Google Maps API key with Directions API enabled:
       https://console.cloud.google.com/apis/library/directions-backend.googleapis.com
    2. Copy config.example.json to config.json and add your API key + destinations.
    3. Run: python3 commute_eta.py
"""

import json
import os
import sys
import time
import threading
import subprocess
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

import rumps
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".commute_eta"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "commute_eta.log"

DEFAULT_CONFIG = {
    "api_key": "YOUR_GOOGLE_MAPS_API_KEY",
    "poll_interval_seconds": 300,
    "active_hours": [
        {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "06:00", "end": "09:00", "show_destination": 1},
        {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "15:00", "end": "19:00", "show_destination": 0},
    ],
    "notifications": {
        "enabled": True,
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
    ],
    "show_route_index": 0,
    "departure_time": "now"
}

DAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
}


def load_config():
    """Load config from ~/.commute_eta/config.json, creating defaults if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return None

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    if config.get("api_key", "").startswith("YOUR_"):
        return None

    return config


def is_active_now(active_hours):
    """Check if the current time falls within any active window.
    Returns (True, window_dict) if active, (False, None) if not.
    """
    if not active_hours:
        return True, None

    now = datetime.now()
    current_day = now.weekday()
    current_time = now.strftime("%H:%M")

    for window in active_hours:
        days = window.get("days", [])
        start = window.get("start", "00:00")
        end = window.get("end", "23:59")

        day_nums = [DAY_MAP.get(d.lower()[:3], -1) for d in days]
        if current_day in day_nums and start <= current_time <= end:
            return True, window

    return False, None


def next_active_time(active_hours):
    """Return a human-readable string for when the next active window starts."""
    if not active_hours:
        return None

    now = datetime.now()
    current_day = now.weekday()
    current_time = now.strftime("%H:%M")

    for day_offset in range(8):
        check_day = (current_day + day_offset) % 7
        for window in active_hours:
            days = window.get("days", [])
            start = window.get("start", "00:00")
            day_nums = [DAY_MAP.get(d.lower()[:3], -1) for d in days]

            if check_day in day_nums:
                if day_offset == 0 and start > current_time:
                    return f"today at {start}"
                elif day_offset == 1:
                    return f"tomorrow at {start}"
                elif day_offset > 0:
                    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    return f"{day_names[check_day]} at {start}"

    return None


def log(msg):
    """Append a timestamped line to the log file."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} | {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_minutes(seconds):
    """Convert seconds to a compact time string."""
    mins = round(seconds / 60)
    if mins >= 60:
        h = mins // 60
        m = mins % 60
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{mins}m"


def compute_leave_by(arrive_by_str, travel_seconds):
    """Given a target arrival time (HH:MM) and travel seconds, return leave-by time string."""
    try:
        now = datetime.now()
        arrive_time = datetime.strptime(arrive_by_str, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        leave_time = arrive_time - timedelta(seconds=travel_seconds)
        if leave_time < now:
            return None  # Already too late
        return leave_time.strftime("%-I:%M %p")
    except (ValueError, TypeError):
        return None


def trend_indicator(current_seconds, previous_seconds):
    """Return a trend string with actual change, e.g. ' +5m' or ' -3m'."""
    if previous_seconds is None:
        return ""
    diff = current_seconds - previous_seconds
    diff_mins = round(abs(diff) / 60)
    if diff > 120:       # > 2 min worse
        return f" ▲{diff_mins}m"
    elif diff < -120:    # > 2 min better
        return f" ▼{diff_mins}m"
    else:
        return ""  # Steady — no clutter


# ---------------------------------------------------------------------------
# Google Maps API
# ---------------------------------------------------------------------------

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def fetch_eta(api_key, origin, destination, departure_time="now"):
    """
    Call Google Maps Directions API and return a list of route dicts or an error dict.
    """
    params = {
        "origin": origin,
        "destination": destination,
        "departure_time": departure_time,
        "traffic_model": "best_guess",
        "alternatives": "true",
        "key": api_key,
    }

    try:
        resp = requests.get(DIRECTIONS_URL, params=params, timeout=15)
        data = resp.json()
    except requests.RequestException as e:
        return {"status": "error", "error": str(e)}

    if data.get("status") != "OK":
        return {
            "status": "error",
            "error": data.get("error_message", data.get("status", "Unknown error")),
        }

    routes = []
    for route in data.get("routes", []):
        leg = route["legs"][0]
        info = {
            "status": "ok",
            "summary": route.get("summary", ""),
            "duration_text": leg["duration"]["text"],
            "duration_seconds": leg["duration"]["value"],
        }
        if "duration_in_traffic" in leg:
            info["traffic_text"] = leg["duration_in_traffic"]["text"]
            info["traffic_seconds"] = leg["duration_in_traffic"]["value"]
        else:
            info["traffic_text"] = info["duration_text"]
            info["traffic_seconds"] = info["duration_seconds"]

        routes.append(info)

    if not routes:
        return {"status": "error", "error": "No routes found"}

    return routes


def traffic_label(normal_sec, traffic_sec):
    """Return a severity label based on how much traffic adds."""
    if traffic_sec <= normal_sec * 1.05:
        return "clear"
    elif traffic_sec <= normal_sec * 1.25:
        return "moderate"
    elif traffic_sec <= normal_sec * 1.50:
        return "heavy"
    else:
        return "severe"


TRAFFIC_ICONS = {
    "clear": "🟢",
    "moderate": "🟡",
    "heavy": "🟠",
    "severe": "🔴",
}

SLEEP_ICON = "😴"


# ---------------------------------------------------------------------------
# Menu Bar App
# ---------------------------------------------------------------------------

class CommuteETA(rumps.App):
    def __init__(self):
        super().__init__("⏳", quit_button=None)

        self.config = load_config()

        if self.config is None:
            self.title = "⚠️ ETA"
            self.menu = [
                rumps.MenuItem("Config needed — click to open", callback=self.open_config),
                rumps.MenuItem(f"Edit: {CONFIG_FILE}", callback=self.open_config),
                None,
                rumps.MenuItem("Quit", callback=rumps.quit_application),
            ]
            return

        self.poll_interval = self.config.get("poll_interval_seconds", 300)
        self.destinations = self.config.get("destinations", [])
        self.active_hours = self.config.get("active_hours", [])
        self.api_key = self.config["api_key"]
        self.show_index = self.config.get("show_route_index", 0)
        self.arrive_by = self.config.get("arrive_by", {})
        self.notif_config = self.config.get("notifications", {"enabled": True, "spike_threshold_minutes": 15})
        self.last_results = {}
        self.last_update = None
        self.is_sleeping = False
        self.is_paused = False

        # Track previous best times for trend arrows and spike detection
        self.previous_best = {}   # idx -> traffic_seconds from last poll

        # ── Menu layout ──────────────────────────────────────────────────

        # Destination items
        self.dest_items = {}
        for i, dest in enumerate(self.destinations):
            icon = dest.get("icon", "📍")
            name = dest.get("name", f"Dest {i}")
            item = rumps.MenuItem(f"{icon} {name}: waiting…")
            item.set_callback(self.make_dest_callback(i))
            self.dest_items[i] = item
            self.menu.add(item)

        self.menu.add(None)

        # Leave-by item
        self.leave_by_item = rumps.MenuItem("")
        self.menu.add(self.leave_by_item)

        self.menu.add(None)

        # Status section
        self.toggle_item = rumps.MenuItem("⏸ Pause", callback=self.toggle_polling)
        self.menu.add(self.toggle_item)

        self.schedule_item = rumps.MenuItem("")
        self.menu.add(self.schedule_item)

        self.status_item = rumps.MenuItem("Last update: —")
        self.menu.add(self.status_item)

        self.menu.add(None)

        # Actions
        self.menu.add(rumps.MenuItem("Refresh Now", callback=self.manual_refresh))
        self.menu.add(rumps.MenuItem("Open Config", callback=self.open_config))
        self.menu.add(rumps.MenuItem("Open in Google Maps", callback=self.open_gmaps))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

        # Start polling
        self.start_poll()

    # ── Polling ──────────────────────────────────────────────────────────

    def start_poll(self):
        """Kick off the repeating poll timer."""
        self.poll_timer = rumps.Timer(self.poll_tick, 60)
        self.poll_timer.start()
        self._seconds_since_last_poll = self.poll_interval
        self.poll_tick(None)

    def poll_tick(self, _):
        if self.is_paused:
            return

        active, window = is_active_now(self.active_hours)

        if not active:
            if not self.is_sleeping:
                self.is_sleeping = True
                nxt = next_active_time(self.active_hours)
                if nxt:
                    self.schedule_item.title = f"💤 Sleeping — next: {nxt}"
                else:
                    self.schedule_item.title = "💤 Sleeping — no upcoming windows"
                self.title = SLEEP_ICON
                self.leave_by_item.title = ""
                log("Entering sleep mode (outside active hours)")
            return

        # We're in an active window
        if self.is_sleeping:
            self.is_sleeping = False
            self.schedule_item.title = "🟢 Active"
            self._seconds_since_last_poll = self.poll_interval
            log("Waking up (entering active hours)")

        # Auto-switch destination based on active window config
        if window and "show_destination" in window:
            new_index = window["show_destination"]
            if new_index != self.show_index and new_index < len(self.destinations):
                self.show_index = new_index
                dest_name = self.destinations[new_index].get("name", "")
                log(f"Auto-switched to destination {new_index}: {dest_name}")

        self._seconds_since_last_poll = getattr(self, "_seconds_since_last_poll", 0) + 60

        if self._seconds_since_last_poll >= self.poll_interval:
            self._seconds_since_last_poll = 0
            threading.Thread(target=self.fetch_all, daemon=True).start()

    def fetch_all(self):
        idx = self.show_index
        if idx >= len(self.destinations):
            return

        dest = self.destinations[idx]
        result = fetch_eta(
            self.api_key,
            dest["origin"],
            dest["destination"],
        )

        # ── Spike detection + trend tracking ─────────────────────────
        if isinstance(result, list) and len(result) > 0:
            best = min(result, key=lambda r: r["traffic_seconds"])
            current_best_sec = best["traffic_seconds"]
            prev_sec = self.previous_best.get(idx)

            # Check for traffic spike notification
            if prev_sec is not None and self.notif_config.get("enabled", True):
                spike_threshold = self.notif_config.get("spike_threshold_minutes", 15) * 60
                increase = current_best_sec - prev_sec
                if increase >= spike_threshold:
                    dest_name = dest.get("name", "")
                    rumps.notification(
                        title="Traffic Spike",
                        subtitle=dest_name,
                        message=f"Drive time jumped to {best['traffic_text']} (+{format_minutes(increase)})",
                    )
                    log(f"Spike notification: {dest_name} +{format_minutes(increase)}")

            self.previous_best[idx] = current_best_sec

        self.last_results[idx] = result
        self.update_menu_item(idx, dest, result)

        self.last_update = datetime.now()
        self.status_item.title = f"Updated {self.last_update.strftime('%-I:%M %p')}"
        log(f"Poll complete: {dest['name']}")

        self.update_title()
        self.update_leave_by()

    # ── Display ──────────────────────────────────────────────────────────

    def update_menu_item(self, idx, dest, result):
        icon = dest.get("icon", "📍")
        name = dest.get("name", f"Dest {idx}")

        if isinstance(result, list) and len(result) > 0:
            best = min(result, key=lambda r: r["traffic_seconds"])
            severity = traffic_label(best["duration_seconds"], best["traffic_seconds"])
            traffic_icon = TRAFFIC_ICONS.get(severity, "")
            compact_time = format_minutes(best["traffic_seconds"])

            # Trend indicator
            prev = self.previous_best.get(idx)
            trend = trend_indicator(best["traffic_seconds"], prev) if prev else ""

            label = f"{icon} {name}: {compact_time}{trend} {traffic_icon}"
            if best.get("summary"):
                label += f"  via {best['summary']}"

            if len(result) > 1:
                alts = []
                for r in result:
                    if r != best:
                        s = traffic_label(r["duration_seconds"], r["traffic_seconds"])
                        alt_time = format_minutes(r["traffic_seconds"])
                        alts.append(
                            f"    ↳ {alt_time} {TRAFFIC_ICONS.get(s, '')} via {r.get('summary', '?')}"
                        )
                label += "\n" + "\n".join(alts)

            self.dest_items[idx].title = label

        elif isinstance(result, dict) and result.get("status") == "error":
            self.dest_items[idx].title = f"{icon} {name}: ⚠️ {result['error'][:40]}"
            log(f"Error for {name}: {result['error']}")

    def update_title(self):
        """Set the menu bar title to the selected destination's ETA."""
        idx = self.show_index
        result = self.last_results.get(idx)
        dest = self.destinations[idx] if idx < len(self.destinations) else None

        if dest is None or result is None:
            self.title = "⏳"
            return

        if isinstance(result, list) and len(result) > 0:
            best = min(result, key=lambda r: r["traffic_seconds"])
            severity = traffic_label(best["duration_seconds"], best["traffic_seconds"])
            traffic_icon = TRAFFIC_ICONS.get(severity, "")
            compact_time = format_minutes(best["traffic_seconds"])

            # Trend indicator in title bar
            prev = self.previous_best.get(idx)
            trend = trend_indicator(best["traffic_seconds"], prev) if prev else ""

            short_name = dest.get("icon", "") or dest.get("name", "")[:3]
            self.title = f"{short_name} {compact_time}{trend} {traffic_icon}"
        elif isinstance(result, dict) and result.get("status") == "error":
            self.title = "⚠️ ETA"
        else:
            self.title = "⏳"

    def update_leave_by(self):
        """Update the leave-by time in the dropdown."""
        idx = self.show_index
        result = self.last_results.get(idx)
        dest = self.destinations[idx] if idx < len(self.destinations) else None

        if dest is None or result is None:
            self.leave_by_item.title = ""
            return

        dest_name = dest.get("name", "")
        arrive_by_str = self.arrive_by.get(dest_name)

        if not arrive_by_str:
            self.leave_by_item.title = ""
            return

        if isinstance(result, list) and len(result) > 0:
            best = min(result, key=lambda r: r["traffic_seconds"])
            leave_time = compute_leave_by(arrive_by_str, best["traffic_seconds"])
            # Convert arrive_by to 12-hour display
            try:
                arrive_display = datetime.strptime(arrive_by_str, "%H:%M").strftime("%-I:%M %p")
            except ValueError:
                arrive_display = arrive_by_str
            if leave_time:
                self.leave_by_item.title = f"🕐 Leave by {leave_time} to arrive by {arrive_display}"
            else:
                self.leave_by_item.title = f"🕐 Leave now — cutting it close for {arrive_display}"
        else:
            self.leave_by_item.title = ""

    # ── Callbacks ────────────────────────────────────────────────────────

    def make_dest_callback(self, idx):
        """Return a callback that sets this destination as the title-bar display."""
        def callback(_):
            self.show_index = idx
            self.update_title()
            self.update_leave_by()
            self.config["show_route_index"] = idx
            try:
                with open(CONFIG_FILE, "w") as f:
                    json.dump(self.config, f, indent=2)
            except Exception:
                pass
        return callback

    def manual_refresh(self, _):
        """Force a refresh regardless of active hours or pause state."""
        self.title = "⏳"
        threading.Thread(target=self.fetch_all, daemon=True).start()

    def toggle_polling(self, _):
        """Toggle polling on/off. Stays in menu bar either way."""
        if self.is_paused:
            self.is_paused = False
            self.toggle_item.title = "⏸ Pause"
            self.schedule_item.title = "🟢 Active"
            self._seconds_since_last_poll = self.poll_interval
            log("Polling resumed (manual toggle)")
        else:
            self.is_paused = True
            self.toggle_item.title = "▶ Resume"
            self.schedule_item.title = "⏸ Paused"
            self.title = "⏸"
            log("Polling paused (manual toggle)")

    def open_config(self, _):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            with open(CONFIG_FILE, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        subprocess.run(["open", str(CONFIG_FILE)])

    def open_gmaps(self, _):
        """Open Google Maps directions for the selected destination."""
        idx = self.show_index
        if idx < len(self.destinations):
            dest = self.destinations[idx]
            origin = requests.utils.quote(dest["origin"])
            destination = requests.utils.quote(dest["destination"])
            url = f"https://www.google.com/maps/dir/{origin}/{destination}"
            subprocess.run(["open", url])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = CommuteETA()
    app.run()
