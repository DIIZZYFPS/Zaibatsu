"""
Configuration and Theme settings for Zaibatsu.
"""

from typing import Dict, Any

# General Config
DEFAULT_THEME = "cyberpunk"
DEFAULT_UPDATE_INTERVAL = 0.5  # in seconds
MAX_BUILDINGS = 12             # Maximum processes shown on screen
MIN_COLS = 80
MIN_ROWS = 24

# Themes definition
# Rich uses console styling, e.g. "bold red", "bright_cyan", "rgb(255,0,128)", etc.
THEMES: Dict[str, Dict[str, Any]] = {
    "cyberpunk": {
        "sky_bg": "black",
        "sky_stars": ["dim white", "white", "bright_white"],
        "cloud": "bright_purple",
        "lightning": "bold bright_yellow",
        "moon": "bright_cyan",
        "moon_glow": "cyan",
        "road": "purple",
        "road_border": "bright_purple",
        "car": "bright_yellow",
        "car_headlight": "white",
        "building_fill": "bright_black",      # Dark body of building
        "building_border": "bright_blue",
        "window_on": "bright_magenta",
        "window_off": "bright_black",
        "selected_border": "bold bright_yellow",
        "selected_fill": "rgb(40,40,40)",
        "dashboard_border": "bright_cyan",
        "dashboard_title": "bold bright_magenta",
        "text_primary": "white",
        "text_secondary": "bright_cyan",
        "text_accent": "bright_magenta",
        "text_warning": "bold red",
        "text_success": "bold green",
        "ambient_sky": "neon_ads",
    },
    "matrix": {
        "sky_bg": "black",
        "sky_stars": ["dim green", "green", "bright_green"],
        "cloud": "dim green",
        "lightning": "bold bright_green",
        "moon": "bright_green",
        "moon_glow": "green",
        "road": "green",
        "road_border": "bright_green",
        "car": "bright_green",
        "car_headlight": "white",
        "building_fill": "black",
        "building_border": "green",
        "window_on": "bright_green",
        "window_off": "dim green",
        "selected_border": "bold bright_white",
        "selected_fill": "rgb(0,20,0)",
        "dashboard_border": "green",
        "dashboard_title": "bold bright_green",
        "text_primary": "bright_green",
        "text_secondary": "green",
        "text_accent": "bold bright_white",
        "text_warning": "bold red",
        "text_success": "bold bright_green",
        "ambient_sky": "matrix_rain",
    },
    "sunset": {
        "sky_bg": "black",
        "sky_stars": ["dim yellow", "yellow", "orange"],
        "cloud": "bright_red",
        "lightning": "bold bright_white",
        "moon": "bright_yellow",
        "moon_glow": "orange",
        "road": "rgb(120,40,40)",
        "road_border": "orange",
        "car": "bright_white",
        "car_headlight": "bright_yellow",
        "building_fill": "rgb(30,10,20)",
        "building_border": "bright_red",
        "window_on": "bright_yellow",
        "window_off": "rgb(80,30,50)",
        "selected_border": "bold orange",
        "selected_fill": "rgb(60,20,40)",
        "dashboard_border": "orange",
        "dashboard_title": "bold orange",
        "text_primary": "white",
        "text_secondary": "orange",
        "text_accent": "bright_red",
        "text_warning": "bold red",
        "text_success": "bold green",
        "ambient_sky": "shooting_stars",
    }
}
