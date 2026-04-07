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
from datetime import datetime, timedelta
from pathlib import Path

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
    "destinations": [
        {
            "name": "Home",
            "origin": "Burbank, CA",
            "destination": "Hemet, CA",
            "icon": "🏠"
        },
        {
            "name": "Office",
            "origin": "Hemet, CA",
            "destination": "Burbank, CA",
            "icon": "🏢"
        }
    ],
    "show_route_index": 0,
    "departure_time": "now"
}


def load_config():
    """Load config from ~/.commute_eta/config.json, creating defaults if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return None  # Signal that config needs to be set up

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    if config.get("api_key", "").startswith("YOUR_"):
        return None

    return config


def log(msg):
    """Append a timestamped line to the log file."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} | {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Google Maps API
# ---------------------------------------------------------------------------

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def fetch_eta(api_key, origin, destination, departure_time="now"):
    """
    Call Google Maps Directions API and return a dict with:
        duration_text:    e.g. "1 hr 42 min"
        duration_seconds: int
        traffic_text:     e.g. "1 hr 58 min"  (with traffic)
        traffic_seconds:  int
        summary:          route name, e.g. "CA-91 E"
        status:           "ok" | "error"
        error:            error message if status == "error"
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
        # duration_in_traffic is only present for driving with departure_time
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
        self.api_key = self.config["api_key"]
        self.show_index = self.config.get("show_route_index", 0)
        self.last_results = {}
        self.last_update = None

        # Build menu skeleton
        self.dest_items = {}
        for i, dest in enumerate(self.destinations):
            icon = dest.get("icon", "📍")
            name = dest.get("name", f"Dest {i}")
            item = rumps.MenuItem(f"{icon} {name}: fetching…")
            item.set_callback(self.make_dest_callback(i))
            self.dest_items[i] = item
            self.menu.add(item)

        self.menu.add(None)  # separator

        self.status_item = rumps.MenuItem("Last update: —")
        self.menu.add(self.status_item)

        self.menu.add(None)

        self.menu.add(rumps.MenuItem("Refresh Now", callback=self.manual_refresh))
        self.menu.add(rumps.MenuItem("Open Config", callback=self.open_config))
        self.menu.add(rumps.MenuItem("Open in Google Maps", callback=self.open_gmaps))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

        # Initial fetch in background
        self.start_poll()

    # -- Polling ---------------------------------------------------------------

    def start_poll(self):
        """Kick off the repeating poll timer."""
        self.poll_timer = rumps.Timer(self.poll_tick, self.poll_interval)
        self.poll_timer.start()
        # Also do an immediate fetch
        threading.Thread(target=self.fetch_all, daemon=True).start()

    def poll_tick(self, _):
        threading.Thread(target=self.fetch_all, daemon=True).start()

    def fetch_all(self):
        for i, dest in enumerate(self.destinations):
            result = fetch_eta(
                self.api_key,
                dest["origin"],
                dest["destination"],
            )
            self.last_results[i] = result
            self.update_menu_item(i, dest, result)

        self.last_update = datetime.now()
        self.status_item.title = f"Updated {self.last_update.strftime('%I:%M %p')}"
        log(f"Poll complete: {len(self.destinations)} destinations")

        # Update title bar with the selected destination
        self.update_title()

    def update_menu_item(self, idx, dest, result):
        icon = dest.get("icon", "📍")
        name = dest.get("name", f"Dest {idx}")

        if isinstance(result, list) and len(result) > 0:
            best = min(result, key=lambda r: r["traffic_seconds"])
            severity = traffic_label(best["duration_seconds"], best["traffic_seconds"])
            traffic_icon = TRAFFIC_ICONS.get(severity, "")

            label = f"{icon} {name}: {best['traffic_text']} {traffic_icon}"
            if best.get("summary"):
                label += f"  via {best['summary']}"

            # Add alternate routes as sub-info
            if len(result) > 1:
                alts = []
                for r in result:
                    if r != best:
                        s = traffic_label(r["duration_seconds"], r["traffic_seconds"])
                        alts.append(
                            f"    ↳ {r['traffic_text']} {TRAFFIC_ICONS.get(s, '')} via {r.get('summary', '?')}"
                        )
                label += "\n" + "\n".join(alts)  # rumps may truncate, but worth trying

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
            short_name = dest.get("icon", "") or dest.get("name", "")[:3]
            self.title = f"{short_name} {best['traffic_text']} {traffic_icon}"
        elif isinstance(result, dict) and result.get("status") == "error":
            self.title = "⚠️ ETA"
        else:
            self.title = "⏳"

    # -- Callbacks -------------------------------------------------------------

    def make_dest_callback(self, idx):
        """Return a callback that sets this destination as the title-bar display."""
        def callback(_):
            self.show_index = idx
            self.update_title()
            # Persist preference
            self.config["show_route_index"] = idx
            try:
                with open(CONFIG_FILE, "w") as f:
                    json.dump(self.config, f, indent=2)
            except Exception:
                pass
        return callback

    def manual_refresh(self, _):
        self.title = "⏳"
        threading.Thread(target=self.fetch_all, daemon=True).start()

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

    # -- Alt routes in dropdown ------------------------------------------------


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = CommuteETA()
    app.run()
