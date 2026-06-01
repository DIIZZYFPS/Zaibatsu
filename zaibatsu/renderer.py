"""
Cityscape Rendering Engine for Zaibatsu.
Implements pseudo-3D isometric cabinet projection buildings, staggered grid, 
multiple streets with dynamic traffic, moon, stars, lightning, and 3D collapse demolition.
Supports process classification (Districts), Helicopter Patrol, and Kaiju Demolition modes.
"""

import math
import random
import time
from typing import Dict, List, Any, Tuple, Optional
from rich.panel import Panel
from rich.text import Text
from rich.align import Align

from zaibatsu.config import THEMES

class DemolitionState:
    """Tracks the state of a building undergoing demolition."""
    def __init__(self, pid: int, name: str, height: int, col_start: int, width: int, depth: int, ground_y: int):
        self.pid = pid
        self.name = name
        self.max_height = height
        self.col_start = col_start
        self.width = width
        self.depth = depth
        self.ground_y = ground_y
        self.frame = 0
        self.max_frames = 6
        self.particles: List[Tuple[int, int, str, str]] = [] # list of (r, c, char, style)

class CityRenderer:
    def __init__(self, theme_name: str = "cyberpunk"):
        self.theme_name = theme_name
        self.theme = THEMES.get(theme_name, THEMES["cyberpunk"])
        
        # Animation states
        self.tick_count = 0
        self.stars: List[Tuple[float, float, str]] = []
        self.clouds: List[Dict[str, Any]] = []
        self.lightning_active = 0
        self.lightning_path: List[Tuple[int, int]] = []
        
        # 5 lanes of cars (one for each street behind/below building rows)
        self.cars: Dict[int, List[Dict[str, Any]]] = {}
        
        # Selected building grid coordinates (row, col)
        self.selected_row = 2
        self.selected_col = 0
        self.cols = 4  # Dynamically calculated during render
        self.rows = 3  # Dynamically calculated during render
        
        # Ongoing demolitions
        self.demolitions: Dict[int, DemolitionState] = {}
        
        # Saved coordinates for navigation
        self.last_building_positions: List[Tuple[int, int, int, int, int, int, Dict[str, Any]]] = []

        # Pre-allocated canvas buffer (reused across frames to reduce GC pressure)
        self._canvas: List[List[Tuple[str, str]]] = []
        self._canvas_size: Tuple[int, int] = (0, 0)

        # Dedicated RNG for deterministic window flicker (isolated from global random state)
        self._window_rng = random.Random()

        # Smooth building height lerping (PID -> current displayed height)
        self._height_lerp: Dict[int, float] = {}

        # Event ticker state
        self.event_log: List[Tuple[float, str]] = []  # (timestamp, message)
        self._ticker_offset = 0
        self._prev_pids: set = set()

        # Ambient sky effects
        self._matrix_rain: List[Dict[str, Any]] = []  # columns of falling chars
        self._neon_ads: List[Dict[str, Any]] = []  # floating ad banners
        self._shooting_stars: List[Dict[str, Any]] = []  # diagonal streaks

    def set_theme(self, theme_name: str):
        if theme_name in THEMES:
            self.theme_name = theme_name
            self.theme = THEMES[theme_name]

    def _initialize_sky_elements(self, width: int, height: int):
        if not self.stars or len(self.stars) < width // 4:
            self.stars = []
            star_chars = [".", "+", "*"]
            for _ in range(width // 3):
                self.stars.append((
                    random.uniform(0, height * 0.35),
                    random.uniform(0, width),
                    random.choice(star_chars)
                ))
        
        if not self.clouds or len(self.clouds) < 3:
            self.clouds = []
            cloud_shapes = ["(~~~~~)", "( ░░░ )", "(█████)", "(  ▒▒  )"]
            for i in range(3):
                self.clouds.append({
                    "x": random.uniform(0, width),
                    "y": random.randint(1, int(height * 0.25)),
                    "width": len(cloud_shapes[i % len(cloud_shapes)]),
                    "shape": cloud_shapes[i % len(cloud_shapes)]
                })

    def _get_process_district(self, proc: Dict[str, Any], slum_rss_threshold: int = 60 * 1024 * 1024) -> str:
        """Classify a process into government (core), industrial (developer), slum (idle), or commercial."""
        name = proc["name"].lower()
        username = (proc.get("username") or "").lower()
        cpu = proc.get("cpu_percent", 0.0)
        mem_rss = proc.get("memory_rss", 0)
        
        # 1. Government District (System core/services)
        # Windows system users
        system_users_win = ("system", "local service", "network service", "nt authority")
        # Linux/macOS system users
        system_users_unix = ("root", "daemon", "nobody", "systemd", "www-data", "_windowserver", "messagebus", "avahi", "syslog", "dbus")
        system_users = system_users_win + system_users_unix
        
        # Windows system process names
        system_names_win = ("svchost", "lsass", "csrss", "services", "smss", "wininit", "spoolsv")
        # Linux system process names
        system_names_unix = ("systemd", "kworker", "ksoftirqd", "kthreadd", "init", "rcu", "migration", "watchdog", "irq/", "jbd2", "dbus-daemon", "networkmanager", "snapd", "cron", "sshd", "udevd")
        system_names = ("system",) + system_names_win + system_names_unix
        
        if any(u in username for u in system_users) or any(sn in name for sn in system_names):
            return "government"
            
        # 2. Industrial District (Compilers, developer tools, DB engines)
        ind_keywords = ("python", "node", "java", "docker", "postgres", "mysql", "git", "code", "cargo", "rust", "csc", "msbuild", "compiler", "engine", "npm", "yarn", "webpack", "nginx", "apache", "redis", "mongo", "go", "gcc", "make", "cmake", "ruby", "perl", "php")
        if any(kw in name for kw in ind_keywords):
            return "industrial"
            
        # 3. Slum District (Inactive / Idle background user tasks)
        # Uses adaptive threshold: bottom quartile of RSS among visible processes.
        # This prevents Linux (where processes use much less RAM) from classifying everything as slum.
        if cpu < 0.5 and mem_rss < slum_rss_threshold:
            return "slum"
            
        # 4. Commercial District (Active user applications)
        return "commercial"

    def render_city(
        self, 
        width: int, 
        height: int, 
        processes: List[Dict[str, Any]], 
        system_stats: Dict[str, Any],
        sort_by: str,
        search_query: str,
        patrol_mode: bool = False,
        heli_coords: Tuple[int, int] = (0, 0),
        kaiju_active: bool = False,
        kaiju_frame: int = 0,
        kaiju_target_pid: int = 0,
        kaiju_target_x: int = -1,
        kaiju_target_y: int = -1,
        orbital_active: bool = False,
        orbital_frame: int = 0,
        orbital_target_x: int = -1,
        orbital_target_y: int = -1,
        orbital_target_width: int = 6,
        dt: float = 0.1
    ) -> Text:
        """Renders the top-down 3D isometric staggered grid cityscape."""
        self.tick_count += 1
        
        if width < 10 or height < 5:
            return Text("Terminal too small", style="bold red")

        # Initialize sky
        self._initialize_sky_elements(width, height)
        
        # Reuse canvas buffer (only reallocate on resize)
        sky_cell = (" ", self.theme["sky_bg"])
        if (width, height) != self._canvas_size:
            self._canvas = [[sky_cell] * width for _ in range(height)]
            self._canvas_size = (width, height)
        else:
            for row in self._canvas:
                for i in range(width):
                    row[i] = sky_cell
        canvas = self._canvas

        # 1. Draw Stars
        for r_f, c_f, char in self.stars:
            r = int(r_f)
            c = int(c_f)
            if 0 <= r < height and 0 <= c < width:
                star_style = self.theme["sky_stars"][0]
                if (self.tick_count + int(c_f * 7)) % 3 == 0:
                    star_style = self.theme["sky_stars"][1]
                elif (self.tick_count + int(c_f * 7)) % 5 == 0:
                    star_style = self.theme["sky_stars"][2]
                canvas[r][c] = (char, star_style)

        # 2. Draw Moon
        ram = system_stats.get("ram_percent", 0)
        moon_col = int(width * 0.8)
        if moon_col < width - 12:
            self._draw_moon(canvas, 1, moon_col, ram)

        # 3. Draw Clouds (clip at right edge instead of wrapping individual chars)
        cpu = system_stats.get("cpu_percent", 0)
        cloud_speed = (0.4 + (cpu / 100.0) * 1.2) * (dt / 0.1)
        for cloud in self.clouds:
            cloud["x"] = (cloud["x"] - cloud_speed) % width
            c_x = int(cloud["x"])
            c_y = cloud["y"]
            shape = cloud["shape"]
            for i, char in enumerate(shape):
                pos = c_x + i
                if pos >= width:
                    break
                if 0 <= c_y < height:
                    canvas[c_y][pos] = (char, self.theme["cloud"])

        # 4. Trigger Lightning
        if cpu > 80 and self.lightning_active == 0:
            if random.random() < 0.15:
                self.lightning_active = 2
                self.lightning_path = []
                curr_c = random.randint(10, width - 10)
                for r in range(0, int(height * 0.5)):
                    self.lightning_path.append((r, curr_c))
                    curr_c += random.choice([-1, 0, 1])

        if self.lightning_active > 0:
            for r, c in self.lightning_path:
                if 0 <= r < height and 0 <= c < width:
                    canvas[r][c] = ("⚡" if r % 2 == 0 else "█", self.theme["lightning"])
            self.lightning_active -= 1

        # 4.5 Draw Per-Theme Ambient Sky Effects (Matrix rain / Neon ads / Shooting stars)
        self._render_ambient_sky(canvas, width, height)

        # 5. Grid Configuration Calculations
        # Dynamically compute number of rows that can fit inside the canvas height (min 3, max 5)
        rows = min(5, max(3, (height - 6) // 5))
        self.rows = rows
        
        plot_w = 6
        plot_d = 3  # side depth
        stagger_offset = 3
        
        # Dense horizontal spacing to bring buildings closer together
        horizontal_spacing = 11
        
        # Dynamically compute column counts that can fit inside the canvas width
        usable_w = width - 4
        cols = max(4, (usable_w - (plot_w + plot_d + stagger_offset * 2)) // horizontal_spacing + 1)
        cols = min(8, cols)  # Cap at max 8 columns (24 processes) to prevent clutter
        self.cols = cols

        # Center layout
        total_city_width = (cols - 1) * horizontal_spacing + plot_w + plot_d + stagger_offset * 2
        start_margin = max(1, (width - total_city_width) // 2)

        # Baseline ground Y coordinates for roads
        ground_y_front = height - 2
        
        # --- COMPACT OVERLAP Spacing Upgrade ---
        # Make row spacing tight so buildings overlap. Setting row_spacing to 3 (very compressed)
        # forces buildings in front to overwrite bases of buildings behind.
        row_spacing = 3 
        
        road_y_coords = {}
        for r_idx in range(rows):
            road_y_coords[r_idx] = ground_y_front - (rows - 1 - r_idx) * row_spacing

        # Calculate dynamic maximum building height based on back row space
        ground_y_0 = road_y_coords[0] - 1
        max_b_height = min(18, max(5, ground_y_0 - plot_d - 4))

        # Pre-compute global metric extremes for relative scaling (once per frame, not per building)
        valid_procs = [p for p in processes if p is not None]
        max_cpu = max((p["cpu_percent"] for p in valid_procs), default=0.01)
        max_cpu = max(max_cpu, 0.01)  # avoid division by zero
        max_rss = max((p["memory_rss"] for p in valid_procs), default=1024**3)
        max_rss = max(max_rss, 1)  # avoid division by zero

        # Adaptive slum RSS threshold: use the 25th percentile of visible process RSS.
        # This ensures at most ~25% of non-system/non-industrial processes become slums,
        # regardless of whether we're on Windows (high RSS) or Linux (low RSS).
        rss_values = sorted([p["memory_rss"] for p in valid_procs]) if valid_procs else [0]
        p25_idx = max(0, len(rss_values) // 4 - 1)
        slum_rss_threshold = rss_values[p25_idx] if rss_values else 60 * 1024 * 1024

        # Clear building positions cache
        self.last_building_positions = []
        
        # Map active processes and demolitions to coordinate cells
        grid_data = {}
        for r_idx in range(rows):
            for c_idx in range(cols):
                cell_idx = r_idx * cols + c_idx
                if cell_idx < len(processes):
                    grid_data[(r_idx, c_idx)] = processes[cell_idx]

        # 6. Painter's Algorithm (Draw Back to Front: Row 0 -> Road 0 -> Row 1 -> Road 1 -> Row 2 -> Road 2)
        for r_idx in range(rows):
            # A. Draw the street behind/below this row first
            self._render_lane_traffic(canvas, width, road_y_coords[r_idx], r_idx, system_stats, dt)
            
            # B. Draw all buildings in this row
            for c_idx in range(cols):
                proc = grid_data.get((r_idx, c_idx))
                
                # Compute anchors
                ground_y = road_y_coords[r_idx] - 1  # sits immediately above the road line
                col_start = start_margin + c_idx * horizontal_spacing + r_idx * stagger_offset
                
                if col_start + plot_w + plot_d > width:
                    continue  # bounds check

                is_selected = (not patrol_mode) and (r_idx == self.selected_row and c_idx == self.selected_col)
                
                # Check for demolition animation
                if proc and proc["pid"] in self.demolitions:
                    demo = self.demolitions[proc["pid"]]
                    demo.col_start = col_start
                    demo.ground_y = ground_y
                    if int(demo.frame) < demo.max_frames:
                        self._draw_demolition_3d(canvas, demo, dt)
                        demo.frame += dt / 0.1
                    else:
                        del self.demolitions[proc["pid"]]
                    continue

                if proc:
                    # Classify process district to determine architectural theme
                    district = self._get_process_district(proc, slum_rss_threshold=slum_rss_threshold)

                    # Calculate dimensions: Height (CPU), Width (RAM), Depth (Threads)
                    # Uses pre-computed max_cpu and max_rss from above (not recomputed per building)
                    cpu_percent = proc.get("cpu_percent", 0.0)
                    h_ratio = cpu_percent / max_cpu if max_cpu > 0.01 else 0
                    target_h = int(h_ratio * max_b_height)
                    
                    # Width uses sqrt scaling so low-ratio values still produce visible girth
                    # (linear scaling clusters most Linux processes at minimum width)
                    mem_ratio = proc["memory_rss"] / max_rss if max_rss > 0 else 0
                    b_width = 6 + int(math.sqrt(mem_ratio) * 4)  # ranges from 6 to 10 columns wide
                    
                    # Depth minimum raised to 3 so every building has visible 3D side faces and roof shading
                    threads = proc.get("threads", 1)
                    b_depth = 3 + min(2, (threads - 1) // 4)  # ranges from 3 to 5 rows deep
                    
                    # Apply district-specific size policies
                    if district == "slum":
                        target_h = 4
                        b_width = 5
                        b_depth = 2
                    else:
                        target_h = max(4, min(target_h, max_b_height + 3))

                    # Smooth height lerping — buildings grow/shrink organically instead of snapping
                    pid = proc["pid"]
                    prev_h = self._height_lerp.get(pid, float(target_h))
                    decay_rate = 3.5667
                    lerp_factor = 1.0 - math.exp(-decay_rate * dt)
                    lerp_factor = max(0.01, min(1.0, lerp_factor))
                    smooth_h = prev_h + (target_h - prev_h) * lerp_factor
                    self._height_lerp[pid] = smooth_h
                    b_height = max(4, int(smooth_h))

                    # Save coordinates for CLI navigation/selection mapping
                    self.last_building_positions.append((r_idx, c_idx, col_start, ground_y, b_height, b_width, b_depth, proc))

                    # Draw the Volumetric 3D Building
                    self._draw_building_3d(canvas, col_start, ground_y, b_height, b_width, b_depth, proc, is_selected, district)
                    
                    cursor_w = b_width
                    cursor_h = b_height
                    cursor_d = b_depth
                else:
                    if is_selected:
                        self._draw_vacant_plot_3d(
                            canvas, col_start, ground_y, plot_w, plot_d,
                            self.theme["selected_border"], self.theme["selected_fill"]
                        )
                    cursor_w = plot_w
                    cursor_h = 0
                    cursor_d = plot_d

                # Draw selection cursor/pointer chevron
                if is_selected:
                    arrow_x = col_start + (cursor_w + cursor_d - 3) // 2
                    bounce = int((math.sin(self.tick_count * 0.5) + 1.0) * 0.8) # 0 to 1
                    arrow_y = ground_y - cursor_h - cursor_d - bounce
                    
                    if 0 <= arrow_y < height and 0 <= arrow_x < width:
                        canvas[arrow_y][arrow_x] = ("▼", self.theme["selected_border"])

        # 7. Render Interactive Mini-Games Overlays (Helicopter Searchlights & Godzilla Laser Strikes)
        
        # A. Render Helicopter Patrol Searchlight Beam and Body
        if patrol_mode:
            self._render_helicopter(canvas, width, height, heli_coords)

        # B. Render Kaiju Demolition Stomp & Laser Beam
        if kaiju_active:
            self._render_kaiju(canvas, width, height, kaiju_frame, kaiju_target_pid, kaiju_target_x, kaiju_target_y)

        # Prune stale PIDs from height lerp cache
        active_pids = {p["pid"] for p in valid_procs}
        stale_pids = [pid for pid in self._height_lerp if pid not in active_pids]
        for pid in stale_pids:
            del self._height_lerp[pid]

        # Pass orbital control arguments down into render_city payload definition
        if orbital_active:
            self._render_orbital_strike(
                canvas, width, height, orbital_frame, 
                orbital_target_x, orbital_target_y, orbital_target_width
            )

        # Force the shockwave layer to process last, overriding existing cells completely
        if orbital_active and orbital_frame == 6:
            self._apply_impact_shockwave(canvas, width, height)

        # Convert canvas to Text (span-coalesced for performance)
        # Consecutive cells with the same style are merged into a single append() call
        result_text = Text()
        for r in range(height):
            row = canvas[r]
            if not row:
                result_text.append("\n")
                continue
            run_chars = [row[0][0]]
            run_style = row[0][1]
            for c in range(1, width):
                char, style = row[c]
                if style == run_style:
                    run_chars.append(char)
                else:
                    result_text.append("".join(run_chars), style=run_style)
                    run_chars = [char]
                    run_style = style
            result_text.append("".join(run_chars), style=run_style)
            result_text.append("\n")

        return result_text

    def _draw_vacant_plot_3d(
        self, 
        canvas: List[List[Tuple[str, str]]], 
        X: int, 
        Y: int, 
        W: int, 
        D: int, 
        border_color: str,
        fill_color: str
    ):
        """Draws a flat isometric plot blueprint on the ground to show a vacant slot."""
        back_y = Y - D + 1
        back_x_start = X + D - 1

        # Draw interior of the parallelogram
        for d in range(0, D):
            r = Y - d
            if 0 <= r < len(canvas):
                for c in range(X + d, X + W - 1 + d):
                    if 0 <= c < len(canvas[0]):
                        is_edge = (
                            (r == Y and (X <= c <= X + W - 2)) or
                            (r == back_y and (back_x_start <= c <= back_x_start + W - 2)) or
                            (c == X + d) or
                            (c == X + W - 2 + d)
                        )
                        if not is_edge:
                            canvas[r][c] = (".", fill_color)

        # Draw the front edge
        for c in range(X, X + W - 1):
            if 0 <= Y < len(canvas) and 0 <= c < len(canvas[0]):
                is_left = (c == X)
                is_right = (c == X + W - 2)
                char = "╚" if is_left else ("╝" if is_right else "═")
                canvas[Y][c] = (char, border_color)
        
        # Draw the back edge
        for c in range(back_x_start, back_x_start + W - 1):
            if 0 <= back_y < len(canvas) and 0 <= c < len(canvas[0]):
                is_left = (c == back_x_start)
                is_right = (c == back_x_start + W - 2)
                char = "╔" if is_left else ("╗" if is_right else "═")
                canvas[back_y][c] = (char, border_color)
        
        # Draw the sloped left and right edges
        for d in range(1, D - 1):
            # Left edge sloped
            ly = Y - d
            lx = X + d
            if 0 <= ly < len(canvas) and 0 <= lx < len(canvas[0]):
                canvas[ly][lx] = ("/", border_color)
            
            # Right edge sloped
            ry = Y - d
            rx = X + W - 2 + d
            if 0 <= ry < len(canvas) and 0 <= rx < len(canvas[0]):
                canvas[ry][rx] = ("/", border_color)

    def _draw_building_3d(
        self, 
        canvas: List[List[Tuple[str, str]]], 
        X: int, 
        Y: int, 
        H: int, 
        W: int, 
        D: int, 
        proc: Dict[str, Any], 
        is_selected: bool,
        district: str
    ):
        """Draws a volumetric pseudo-3D building based on its District Classification (visual style)."""
        # Determine theme styling based on District
        border_color = self.theme["selected_border"] if is_selected else self.theme["building_border"]
        fill_color = self.theme["selected_fill"] if is_selected else self.theme["building_fill"]
        shadow_style = self.theme["window_off"]

        # 1. District customization overrides
        front_fill_char = " "
        if district == "government":
            # Brutalist Concrete theme
            border_color = "bold bright_white" if is_selected else "bold rgb(100,100,100)"
            fill_color = "rgb(40,45,40)"
            front_fill_char = "▒" # rough concrete texture
        elif district == "industrial":
            # Industrial factory theme
            border_color = "bold orange" if is_selected else "orange"
            fill_color = "rgb(50,30,10)"
        elif district == "slum":
            # Shacks theme
            border_color = "dim white" if is_selected else "dim gray"
            fill_color = "black"

        # --- A. DRAW FRONT FACE (Flat rectangular wall) ---
        for r in range(Y - H, Y + 1):
            if r >= len(canvas) or r < 0:
                continue
            for c in range(X, X + W - 1):
                if c >= len(canvas[0]) or c < 0:
                    continue
                is_left = (c == X)
                is_right = (c == X + W - 2)
                is_top = (r == Y - H)
                is_bottom = (r == Y)
                
                # Brutalist shapes use heavy double-border characters, slums use simple light borders
                if is_left and is_top:
                    canvas[r][c] = ("╔" if (is_selected or district == "government") else "┌", border_color)
                elif is_right and is_top:
                    canvas[r][c] = ("╦" if (is_selected or district == "government") else "┬", border_color)
                elif is_left and is_bottom:
                    canvas[r][c] = ("╚" if (is_selected or district == "government") else "└", border_color)
                elif is_right and is_bottom:
                    canvas[r][c] = ("╩" if (is_selected or district == "government") else "┴", border_color)
                elif is_top:
                    canvas[r][c] = ("═" if (is_selected or district == "government") else "─", border_color)
                elif is_bottom:
                    canvas[r][c] = ("═" if (is_selected or district == "government") else "─", border_color)
                elif is_left or is_right:
                    canvas[r][c] = ("║" if (is_selected or district == "government") else "│", border_color)
                else:
                    canvas[r][c] = (front_fill_char, fill_color)

        # --- B. DRAW SIDE FACE (Sloped UP and RIGHT) ---
        for d in range(1, D):
            c = X + W - 2 + d
            r_top = Y - H - d
            r_bottom = Y - d
            
            if c >= len(canvas[0]) or c < 0:
                continue
                
            for r in range(r_top, r_bottom + 1):
                if r >= len(canvas) or r < 0:
                    continue
                    
                is_back = (d == D - 1)
                is_top_edge = (r == r_top)
                is_bottom_edge = (r == r_bottom)
                
                if is_top_edge:
                    char = "╗" if (is_back and (is_selected or district == "government")) else ("┐" if is_back else "/")
                    canvas[r][c] = (char, border_color)
                elif is_bottom_edge:
                    char = "╝" if (is_back and (is_selected or district == "government")) else ("┘" if is_back else "/")
                    canvas[r][c] = (char, border_color)
                elif is_back:
                    canvas[r][c] = ("║" if (is_selected or district == "government") else "│", border_color)
                else:
                    # Inner side shading
                    side_texture = "░"
                    if district == "government":
                        side_texture = "▒"
                    canvas[r][c] = (side_texture, shadow_style)

        # --- C. DRAW ROOF FACE (Isometric Parallelogram Top) ---
        for dy in range(1, D):
            r = Y - H - dy
            if r >= len(canvas) or r < 0:
                continue
            for c in range(X + dy, X + W - 1 + dy):
                if c >= len(canvas[0]) or c < 0:
                    continue
                    
                is_back_roof = (dy == D - 1)
                is_left_roof_edge = (c == X + dy)
                is_right_roof_edge = (c == X + W - 2 + dy)
                
                # Special roof shapes (Industrial Factory saw-tooth: '/\/')
                roof_char = "."
                if district == "industrial":
                    roof_char = "v" if (c % 2 == 0) else "^"
                elif district == "government":
                    roof_char = "▒"
                elif district == "slum":
                    roof_char = "x"
                
                if is_left_roof_edge and is_back_roof:
                    canvas[r][c] = ("╔" if (is_selected or district == "government") else "┌", border_color)
                elif is_left_roof_edge:
                    canvas[r][c] = ("/" if (is_selected or district == "government") else "/", border_color)
                elif is_right_roof_edge and is_back_roof:
                    canvas[r][c] = ("╗" if (is_selected or district == "government") else "┐", border_color)
                elif is_right_roof_edge:
                    canvas[r][c] = ("/" if (is_selected or district == "government") else "/", border_color)
                elif is_back_roof:
                    canvas[r][c] = ("═" if (is_selected or district == "government") else "─", border_color)
                else:
                    canvas[r][c] = (roof_char, border_color if district == "industrial" else "dim white")

        # --- D. DRAW NEON PROCESS SIGNS ---
        center_c = X + (W - 2) // 2
        name = proc["name"]
        
        # Gov centers display PIDs, slums display shacks labels
        if district == "slum":
            display_name = "HUT"
        else:
            display_name = name
            
        name_start_r = Y - H + 2
        name_max_len = H - 3
        truncated_name = display_name[:name_max_len] if name_max_len > 0 else ""
        
        for i, char in enumerate(truncated_name):
            curr_r = name_start_r + i
            if 0 <= curr_r < len(canvas) and curr_r < Y and X < center_c < X + W - 2 and 0 <= center_c < len(canvas[0]):
                # Sign color styling
                sign_style = self.theme["text_accent"] if is_selected else self.theme["text_primary"]
                if district == "government":
                    sign_style = "bold green"
                elif district == "industrial":
                    sign_style = "bold bright_yellow"
                    
                canvas[curr_r][center_c] = (char.upper(), sign_style)

        # --- E. DRAW FRONT WINDOWS ---
        cpu_usage = proc["cpu_percent"]
        win_prob = 0.05 + min(0.9, cpu_usage / 100.0)
        if district == "slum":
            win_prob = 0.05 # Slums are dark
            
        for r in range(Y - H + 1, Y):
            for c in range(X + 1, X + W - 2):
                if c in (center_c - 1, center_c, center_c + 1):
                    continue
                if (r % 2 == 1) and (c % 2 == 1):
                    # Use isolated RNG for window flicker (doesn't pollute global random state)
                    self._window_rng.seed(proc["pid"] + r * 13 + c * 37 + (self.tick_count // (max(1, int(15 - min(14, cpu_usage // 7))))))
                    is_on = self._window_rng.random() < win_prob
                    
                    if is_on:
                        win_style = self.theme["window_on"]
                        win_char = "█"
                        
                        if district == "slum":
                            win_char = "x" # broken window
                            win_style = "dim yellow"
                        elif cpu_usage > 50 and (self.tick_count % 2 == 0):
                            win_style = "bold red" if cpu_usage > 80 else "bold bright_yellow"
                            
                        canvas[r][c] = (win_char, win_style)
                    else:
                        canvas[r][c] = ("░", self.theme["window_off"])

        # --- F. DRAW CHIMNEY SMOKE ---
        # Industrial factories release smoke constantly
        io_act = proc["io_activity"]
        if io_act > 1024 or district == "industrial":
            smoke_char = random.choice(["~", "*", "s", "o"])
            smoke_r = Y - H - D
            if 0 <= smoke_r < len(canvas):
                canvas[smoke_r][center_c + D - 1] = (smoke_char, "dim white" if district != "industrial" else "dim orange")

    def _render_lane_traffic(self, canvas: List[List[Tuple[str, str]]], width: int, Y: int, lane_idx: int, system_stats: Dict[str, Any], dt: float = 0.1):
        """Draws the horizontal road line and car traffic for a specific lane."""
        if Y >= len(canvas):
            return
            
        for c in range(width):
            canvas[Y][c] = ("═", self.theme["road_border"])
            
        disk_io = system_stats.get("disk_read_speed", 0) + system_stats.get("disk_write_speed", 0)
        net_io = system_stats.get("net_sent_speed", 0) + system_stats.get("net_recv_speed", 0)
        total_io_mb = (disk_io + net_io) / (1024 * 1024)
        
        traffic_factor = min(8.0, math.log1p(total_io_mb) * 1.5)
        car_speed = 0.5 + traffic_factor * 0.4
        
        lane_cars = self.cars.get(lane_idx, [])
        if not lane_cars:
            for _ in range(random.randint(1, 2)):
                lane_cars.append({
                    "x": random.randint(0, width - 6),
                    "dir": random.choice([1, -1]),
                    "shape": random.choice(["◀■■◀", "◀o-o◀", "▶■■▶", "▶o-o▶"]),
                    "color": random.choice(["bright_yellow", "bright_cyan", "bright_magenta", "bright_red"])
                })
            self.cars[lane_idx] = lane_cars

        spawn_chance = 0.03 + (traffic_factor * 0.08)
        if random.random() < spawn_chance and len(lane_cars) < 4:
            d = random.choice([1, -1])
            shape = random.choice(["▶■■▶", "▶o-o▶"]) if d == 1 else random.choice(["◀■■◀", "◀o-o◀"])
            lane_cars.append({
                "x": 0 if d == 1 else width - 6,
                "dir": d,
                "shape": shape,
                "color": random.choice(["bright_yellow", "bright_cyan", "bright_magenta", "bright_white"])
            })

        active_cars = []
        for car in lane_cars:
            car["x"] += car["dir"] * car_speed * (dt / 0.1)
            cx = int(car["x"])
            
            if 0 <= cx < width - len(car["shape"]):
                active_cars.append(car)
                for i, char in enumerate(car["shape"]):
                    pos = cx + i
                    canvas[Y][pos] = (char, car["color"])
                    
        self.cars[lane_idx] = active_cars

    def _draw_demolition_3d(self, canvas: List[List[Tuple[str, str]]], demo: DemolitionState, dt: float = 0.1):
        """Draws a collapsing 3D building explosion animation."""
        f = demo.frame
        X = demo.col_start
        Y = demo.ground_y
        W = demo.width
        D = demo.depth
        H = demo.max_height

        curr_height = int(H * (1.0 - (f / demo.max_frames)))
        curr_height = max(1, curr_height)

        border_style = "bold red"
        fill_style = "bold yellow"

        # Draw shrinking 3D body shell
        for r in range(Y - curr_height, Y + 1):
            for c in range(X, X + W - 1):
                if c >= len(canvas[0]) or r >= len(canvas):
                    continue
                is_border = (c == X or c == X + W - 2 or r == Y - curr_height or r == Y)
                if is_border:
                    canvas[r][c] = (random.choice(["*", "#", "%", "/"]), border_style)
                else:
                    canvas[r][c] = (random.choice(["@", "x", "░", "█"]), fill_style)

        # Draw sloped side face outline collapsing
        for d in range(1, D):
            c = X + W - 2 + d
            r_top = Y - curr_height - d
            r_bottom = Y - d
            
            if c >= len(canvas[0]) or r_top >= len(canvas):
                continue
                
            for r in range(r_top, r_bottom + 1):
                if r >= len(canvas) or r < 0:
                    break
                is_back = (d == D - 1)
                is_top_edge = (r == r_top)
                
                if is_top_edge or r == r_bottom or is_back:
                    canvas[r][c] = (random.choice(["*", "%", "x", "/"]), border_style)
                else:
                    canvas[r][c] = ("░", "dim red")

        # Spawn falling dust/rubble particles
        if f == 0:
            for _ in range(25):
                pr = random.randint(Y - H - 2, Y)
                pc = random.randint(X - 2, X + W + D)
                pchar = random.choice(["*", "o", "+", "x", "@"])
                pstyle = random.choice(["bold red", "bold yellow", "bold white", "dim gray"])
                demo.particles.append((pr, pc, pchar, pstyle))
        else:
            updated_particles = []
            for pr, pc, pchar, pstyle in demo.particles:
                new_r = pr + random.choice([0, 1, 2]) * (dt / 0.1)
                new_c = pc + random.choice([-1, 0, 1]) * (dt / 0.1)
                if new_r <= Y + D:
                    updated_particles.append((new_r, new_c, pchar, pstyle))
            demo.particles = updated_particles

        # Print particles
        for pr, pc, pchar, pstyle in demo.particles:
            ipr = int(pr)
            ipc = int(pc)
            if 0 <= ipr < len(canvas) and 0 <= ipc < len(canvas[0]):
                canvas[ipr][ipc] = (pchar, pstyle)

        # Rubble pile at base
        rubble_h = int(H * 0.15) + 1
        for r in range(Y - rubble_h, Y + D):
            for c in range(X - 1, X + W + D):
                if 0 <= r < len(canvas) and 0 <= c < len(canvas[0]):
                    canvas[r][c] = (random.choice(["_", ".", "░", "■"]), "dim red" if f % 2 == 0 else "dim gray")

    def _render_helicopter(self, canvas: List[List[Tuple[str, str]]], width: int, height: int, heli_coords: Tuple[int, int]):
        """Renders the controllable patrol helicopter and overlays its yellow searchlight cone."""
        hx, hy = heli_coords
        
        # 1. Draw Searchlight Cone (widening beam filled with transparent/glow characters)
        # We overlay this on the canvas BEFORE drawing the helicopter itself
        beam_style = "bold yellow"
        for i in range(1, height - hy):
            r = hy + i
            if r >= height:
                break
            # Cone spreads out: width at depth i spans from hx + 5 - i to hx + 5 + i
            start_c = max(0, hx + 5 - i)
            end_c = min(width - 1, hx + 5 + i)
            for c in range(start_c, end_c + 1):
                # Overlay characters (keep borders, but color windows or sky spaces dim yellow)
                cur_char, cur_style = canvas[r][c]
                # If there's an active character like borders, color it yellow. If sky space, draw light dust
                if cur_char == " ":
                    canvas[r][c] = (".", "rgb(60,60,0)") # very dim yellow light dust
                elif cur_char in ("│", "║", "─", "═", "┌", "┐", "└", "┘", "╔", "╗", "╚", "╝", "┬", "┴", "╦", "╩"):
                    canvas[r][c] = (cur_char, beam_style)
                elif cur_char == "█":
                    canvas[r][c] = ("█", "bold yellow")

        # 2. Draw Helicopter body (4 lines)
        blade_char = "X" if (self.tick_count % 2 == 0) else "+"
        heli_art = [
            f"   ====={blade_char}=====   ",
            r"     /  [_]  \    ",
            "  ==[*]-[O]-[*]  ",
            "      O---O      "
        ]
        
        for i, line in enumerate(heli_art):
            r = hy + i
            if r >= height:
                break
            for j, char in enumerate(line):
                c = hx + j
                if 0 <= c < width and char != " ":
                    canvas[r][c] = (char, "bold bright_cyan")

    def _render_orbital_strike(
        self, 
        canvas: List[List[Tuple[str, str]]], 
        width: int, 
        height: int, 
        frame: int, 
        target_x: int, 
        target_y: int, 
        b_width: int
    ):
        """Renders the satellite targeting reticle and kinetic column delivery beam."""
        center_x = target_x + (b_width // 2)
        
        # 1. Reticle Convergence Path (Frames 1-4)
        if frame <= 4:
            reticle_style = "bold bright_red" if (self.tick_count % 2 == 0) else "bold red"
            radius = max(2, 8 - (frame * 2))
            
            # Draw linear alignment guides
            for r in range(max(0, target_y - 8), min(height, target_y + 4)):
                if 0 <= center_x < width:
                    canvas[r][center_x] = ("┃", reticle_style)
            for c in range(max(0, center_x - radius * 2), min(width, center_x + radius * 2 + 1)):
                if 0 <= target_y < height:
                    canvas[target_y][c] = ("━", reticle_style)
            
            # Draw bounding corner brackets
            brackets = [
                (target_y - radius, center_x - radius * 2, "▛"),
                (target_y - radius, center_x + radius * 2, "▜"),
                (target_y + radius, center_x - radius * 2, "▙"),
                (target_y + radius, center_x + radius * 2, "▟")
            ]
            for br, bc, glyph in brackets:
                if 0 <= br < height and 0 <= bc < width:
                    canvas[br][bc] = (glyph, reticle_style)

        # 2. High-Energy Column Delivery Path (Frames 5-9)
        elif 5 <= frame <= 9:
            beam_chars = ["█", "▓", "▒", "░"] if frame > 6 else ["█"]
            style = (
                "bold bright_white on rgb(255,255,255)" if frame == 6 else (
                    "bold bright_cyan on rgb(0,80,160)" if frame == 5 else "dim cyan"
                )
            )
            
            # Blast column width narrows as energy dissipates post-impact
            beam_spread = 2 if frame <= 6 else 1
            
            for r in range(0, target_y + 1):
                if r >= height:
                    continue
                for c in range(max(0, center_x - beam_spread), min(width, center_x + beam_spread + 1)):
                    canvas[r][c] = (random.choice(beam_chars), style)

    def _apply_impact_shockwave(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Intercepts the entire canvas buffer post-render and forces style/color inversion."""
        for r in range(height):
            for c in range(width):
                char, style = canvas[r][c]
                if char == " ":
                    canvas[r][c] = ("▒", "bold bright_white on rgb(220,220,220)")
                else:
                    canvas[r][c] = (char, "bold black on bright_white")

    def _render_kaiju(self, canvas: List[List[Tuple[str, str]]], width: int, height: int, frame: int, target_pid: int, target_x: int = -1, target_y: int = -1):
        """Renders the walking Godzilla-style Kaiju dinosaur and its laser strikes."""
        if target_x == -1 or target_y == -1:
            # Find targeted process horizontal coordinates
            target_x = width // 2
            target_y = height - 3
            
            # Look up coordinates of target process from positions cache
            for r, c, col_start, ground_y, b_height, b_width, b_depth, proc in self.last_building_positions:
                if proc["pid"] == target_pid:
                    target_x = col_start
                    target_y = ground_y
                    break
                
        # Walk from left edge. Walks 6 columns per frame, stops at target_x - 10
        stop_x = max(1, target_x - 8)
        kx = min(stop_x, frame * 6)
        
        # Kaiju sits at the target building's ground level
        ky = target_y - 3
        
        # Draw Godzilla (3 lines) using safe ASCII characters
        kaiju_art = [
            "  /\\_/\\  ",
            " ( O.O )__",
            " /  V  \\"
        ]
        for i, line in enumerate(kaiju_art):
            r = ky + i
            if r >= height or r < 0:
                continue
            for j, char in enumerate(line):
                c = kx + j
                if 0 <= c < width and char != " ":
                    canvas[r][c] = (char, "bold green")

        # Laser beam state: once Kaiju stops moving, it fires laser beam
        if kx == stop_x:
            laser_r = ky + 1
            laser_start_c = kx + 10
            laser_end_c = target_x + 1
            
            # Fire laser beam! (using ASCII characters for maximum platform compatibility)
            if 0 <= laser_r < height:
                for c in range(laser_start_c, laser_end_c):
                    if c < width:
                        canvas[laser_r][c] = (random.choice(["=", "*", "%", "#", "@"]), "bold red" if self.tick_count % 2 == 0 else "bold bright_yellow")

    def add_event(self, message: str):
        """Add a timestamped event to the ticker log."""
        import time as _time
        self.event_log.append((_time.time(), message))
        # Keep only last 50 events (older ones scroll off anyway)
        if len(self.event_log) > 50:
            self.event_log = self.event_log[-50:]

    def build_ticker_bar(self, width: int) -> Text:
        """Build a standalone scrolling ticker bar Text renderable for the layout strip."""
        ticker_text = Text()

        # Build ticker string from recent events
        separator = "  ///  "
        ticker_parts = []
        now = time.time()
        for ts, msg in self.event_log:
            if now - ts < 120:  # Show events from the last 2 minutes
                ticker_parts.append(msg)

        if not ticker_parts:
            # Fallback: show a static bar
            bar = " WIRE: ZAIBATSU CITY MONITOR " + "═" * max(0, width - 30)
            ticker_text.append(bar[:width], style="dim bright_cyan")
            return ticker_text

        full_ticker = separator.join(ticker_parts) + separator
        ticker_len = len(full_ticker)

        # Advance scroll offset
        self._ticker_offset = (self._ticker_offset + 1) % max(1, ticker_len)

        # Style based on theme
        ticker_style = "bold bright_cyan" if self.theme_name == "cyberpunk" else (
            "bold bright_green" if self.theme_name == "matrix" else "bold orange"
        )

        prefix = " WIRE: "
        ticker_text.append(prefix, style="bold bright_magenta")

        # Fill remaining width with scrolling text
        remaining = width - len(prefix)
        scroll_chars = []
        for i in range(remaining):
            idx = (i + self._ticker_offset) % ticker_len
            scroll_chars.append(full_ticker[idx])
        ticker_text.append("".join(scroll_chars), style=ticker_style)

        return ticker_text

    def _render_event_ticker(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Renders a scrolling cyberpunk news ticker at the bottom of the canvas."""
        if not self.event_log:
            return

        # Build ticker string from recent events
        separator = "  ///  "
        ticker_parts = []
        now = time.time()
        for ts, msg in self.event_log:
            age = now - ts
            if age < 60:  # Show events from the last 60 seconds
                ticker_parts.append(msg)
        
        if not ticker_parts:
            return

        full_ticker = separator.join(ticker_parts) + separator
        ticker_len = len(full_ticker)
        
        # Scroll offset advances each tick
        self._ticker_offset = (self._ticker_offset + 1) % max(1, ticker_len)
        
        # Render on the front road row (height-2) — height-1 gets clipped by Panel border
        ticker_row = height - 2
        if ticker_row < 0 or ticker_row >= height:
            return
        ticker_style = "bold bright_cyan" if self.theme_name == "cyberpunk" else (
            "bold bright_green" if self.theme_name == "matrix" else "bold orange"
        )
        prefix = " WIRE: "
        prefix_len = len(prefix)
        
        # Draw prefix
        for i, ch in enumerate(prefix):
            if i < width:
                canvas[ticker_row][i] = (ch, "bold bright_magenta")
        
        # Draw scrolling text
        for c in range(prefix_len, width):
            idx = (c - prefix_len + self._ticker_offset) % ticker_len
            canvas[ticker_row][c] = (full_ticker[idx], ticker_style)

    def _render_ambient_sky(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Renders per-theme ambient sky effects above the city."""
        ambient_type = self.theme.get("ambient_sky", None)
        if not ambient_type:
            return

        if ambient_type == "matrix_rain":
            self._render_matrix_rain(canvas, width, height)
        elif ambient_type == "neon_ads":
            self._render_neon_ads(canvas, width, height)
        elif ambient_type == "shooting_stars":
            self._render_shooting_stars(canvas, width, height)

    def _render_matrix_rain(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Falling green character columns for the Matrix theme."""
        # Initialize rain columns if empty
        if not self._matrix_rain or len(self._matrix_rain) < width // 6:
            self._matrix_rain = []
            for _ in range(width // 6):
                self._matrix_rain.append({
                    "x": random.randint(0, width - 1),
                    "y": random.uniform(-height, 0),
                    "speed": random.uniform(0.3, 1.2),
                    "length": random.randint(3, 8),
                    "chars": [chr(random.randint(0x30, 0x39)) for _ in range(8)]
                })

        rain_chars = "0123456789ABCDEFabcdef:;|{}[]"
        for drop in self._matrix_rain:
            drop["y"] += drop["speed"]
            head_y = int(drop["y"])
            
            # Draw the trail
            for i in range(drop["length"]):
                r = head_y - i
                c = drop["x"]
                if 0 <= r < int(height * 0.4) and 0 <= c < width:
                    # Only draw on empty sky cells
                    if canvas[r][c][0] == " ":
                        if i == 0:
                            char = random.choice(list(rain_chars))
                            canvas[r][c] = (char, "bold bright_green")
                        elif i < 3:
                            canvas[r][c] = (random.choice(list(rain_chars)), "green")
                        else:
                            canvas[r][c] = (random.choice(list(rain_chars)), "dim green")
            
            # Reset when off-screen
            if head_y - drop["length"] > height * 0.4:
                drop["y"] = random.uniform(-10, -2)
                drop["x"] = random.randint(0, width - 1)
                drop["speed"] = random.uniform(0.3, 1.2)

    def _render_neon_ads(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Floating neon advertisement banners for the Cyberpunk theme."""
        ad_texts = [
            "DRINK NUKA", "BUY MORE", "OBEY", "UPGRADE NOW",
            "CORP.NET", "ZAIBATSU", "NEON DISTRICT", "SYNTH LIFE",
            "CYBER.IO", "GRID ONLINE"
        ]
        ad_styles = [
            "bold bright_magenta", "bold bright_cyan", "bold bright_yellow",
            "bold bright_red", "bold bright_green"
        ]
        
        # Initialize ads if empty
        if not self._neon_ads:
            for i in range(2):
                self._neon_ads.append({
                    "text": random.choice(ad_texts),
                    "x": random.uniform(0, width),
                    "y": random.randint(1, max(2, int(height * 0.2))),
                    "speed": random.uniform(0.3, 0.8),
                    "style": random.choice(ad_styles)
                })

        for ad in self._neon_ads:
            ad["x"] = (ad["x"] - ad["speed"]) % (width + len(ad["text"]))
            ax = int(ad["x"])
            ay = ad["y"]
            
            # Blinking effect
            if self.tick_count % 20 < 2:
                continue  # blink off
            
            text = f" {ad['text']} "
            for i, ch in enumerate(text):
                c = ax + i
                if 0 <= c < width and 0 <= ay < height:
                    if canvas[ay][c][0] in (" ", ".", "+", "*"):
                        canvas[ay][c] = (ch, ad["style"])

    def _render_shooting_stars(self, canvas: List[List[Tuple[str, str]]], width: int, height: int):
        """Brief diagonal streaks for the Sunset theme."""
        # Spawn new shooting star occasionally
        if random.random() < 0.04 and len(self._shooting_stars) < 2:
            self._shooting_stars.append({
                "x": random.randint(int(width * 0.2), width - 5),
                "y": random.randint(0, max(1, int(height * 0.15))),
                "dx": random.choice([-2, -1]),
                "dy": 1,
                "life": 0,
                "max_life": random.randint(4, 8)
            })

        active = []
        for star in self._shooting_stars:
            star["life"] += 1
            if star["life"] > star["max_life"]:
                continue  # expired
            active.append(star)
            
            # Draw streak trail
            for i in range(min(star["life"], 4)):
                r = star["y"] + star["dy"] * (star["life"] - i)
                c = star["x"] + star["dx"] * (star["life"] - i)
                if 0 <= r < int(height * 0.3) and 0 <= c < width:
                    if canvas[r][c][0] == " ":
                        if i == 0:
                            canvas[r][c] = ("*", "bold bright_white")
                        elif i == 1:
                            canvas[r][c] = ("-", "bright_yellow")
                        else:
                            canvas[r][c] = (".", "dim yellow")
        
        self._shooting_stars = active

    def start_demolition(self, proc: Dict[str, Any], position_info: Tuple[int, int, int, int, int]):
        """Initiate collapse animation tracking."""
        col_start, ground_y, height, width, depth = position_info
        self.demolitions[proc["pid"]] = DemolitionState(
            pid=proc["pid"],
            name=proc["name"],
            height=height,
            col_start=col_start,
            width=width,
            depth=depth,
            ground_y=ground_y
        )

    def _draw_moon(self, canvas: List[List[Tuple[str, str]]], row: int, col: int, ram_percent: float):
        """Draws a moon corresponding to memory utilization."""
        moon_color = self.theme["moon"]
        if ram_percent > 85:
            moon_color = "bold red"
        elif ram_percent > 65:
            moon_color = "bold orange"
            
        glow_color = self.theme["moon_glow"]
        
        if ram_percent < 30:
            moon_art = [
                "   .---.",
                "  /     *",
                "  \\     *",
                "   '---'"
            ]
        elif ram_percent < 60:
            moon_art = [
                "   .---.",
                "  / █   )",
                "  \\ █   )",
                "   '---'"
            ]
        elif ram_percent < 80:
            moon_art = [
                "   .---.",
                "  / ███ )",
                "  \\ ███ )",
                "   '---'"
            ]
        else:
            moon_art = [
                "  .-----. ",
                " / █████ \\",
                " | █████ |",
                " \\ █████ /",
                "  '-----' "
            ]

        for i, line in enumerate(moon_art):
            r = row + i
            for j, char in enumerate(line):
                c = col + j
                if 0 <= r < len(canvas) and 0 <= c < len(canvas[0]):
                    if char in ("█", "/", "\\", "(", ")", "-", "|", "'", "."):
                        style = moon_color if char == "█" else glow_color
                        canvas[r][c] = (char, style)

    def draw_dashboard(
        self, 
        system_stats: Dict[str, Any], 
        selected_proc: Optional[Dict[str, Any]], 
        sort_by: str, 
        search_query: str,
        is_paused: bool,
        is_demo: bool = False
    ) -> Panel:
        """Generates the right/sidebar status dashboard details with system stats."""
        dash = Text()

        # Theme Title
        dash.append(" 🌆 ZAIBATSU CITY MONITOR \n", style=self.theme["dashboard_title"])
        dash.append("=" * 26 + "\n", style=self.theme["dashboard_border"])
        if is_demo:
            dash.append(" ⚠️ DEMO MODE ACTIVE (SAFE) ⚠️\n", style="bold yellow")
            dash.append("=" * 26 + "\n", style=self.theme["dashboard_border"])
        
        # System Stats
        cpu = system_stats.get("cpu_percent", 0)
        ram_pct = system_stats.get("ram_percent", 0)
        ram_used = system_stats.get("ram_used_gb", 0)
        ram_tot = system_stats.get("ram_total_gb", 0)
        
        dash.append("SYSTEM STATE:\n", style="bold " + self.theme["text_secondary"])
        dash.append("  CPU LOAD: ", style=self.theme["text_primary"])
        cpu_color = "red" if cpu > 85 else ("yellow" if cpu > 60 else "green")
        dash.append(f"{cpu:5.1f}% ", style=f"bold {cpu_color}")
        dash.append(self._make_progress_bar(cpu, 10), style=f"bold {cpu_color}")
        dash.append("\n")

        dash.append("  RAM LOAD: ", style=self.theme["text_primary"])
        ram_color = "red" if ram_pct > 85 else ("yellow" if ram_pct > 65 else "green")
        dash.append(f"{ram_pct:5.1f}% ", style=f"bold {ram_color}")
        dash.append(self._make_progress_bar(ram_pct, 10), style=f"bold {ram_color}")
        dash.append(f"\n            ({ram_used:.1f}/{ram_tot:.1f} GB)\n", style="dim white")

        disk_r = system_stats.get("disk_read_speed", 0)
        disk_w = system_stats.get("disk_write_speed", 0)
        net_s = system_stats.get("net_sent_speed", 0)
        net_r = system_stats.get("net_recv_speed", 0)
        
        dash.append(f"  DISK IO:  ", style=self.theme["text_primary"])
        dash.append(f"R: {self._format_speed(disk_r)} | W: {self._format_speed(disk_w)}\n", style=self.theme["text_secondary"])
        dash.append(f"  NET IO:   ", style=self.theme["text_primary"])
        dash.append(f"S: {self._format_speed(net_s)} | R: {self._format_speed(net_r)}\n\n", style=self.theme["text_secondary"])

        # Display View Configurations
        dash.append("CITY MATRIX:\n", style="bold " + self.theme["text_secondary"])
        sort_lbl = "CPU Util" if sort_by == "cpu" else "Memory (RSS)"
        dash.append("  SORT BY:   ", style=self.theme["text_primary"])
        dash.append(f"{sort_lbl}\n", style=self.theme["text_accent"])
        
        status_lbl = "ACTIVE"
        status_style = self.theme["text_success"]
        if is_paused:
            status_lbl = "FROZEN (PAUSED)"
            status_style = self.theme["text_warning"]
        dash.append("  CLOCK:    ", style=self.theme["text_primary"])
        dash.append(f"{status_lbl}\n", style=status_style)

        if search_query:
            dash.append("  FILTER:   ", style=self.theme["text_primary"])
            dash.append(f"'{search_query}'\n", style="bold bright_yellow")
            
        # Target Grid Coords
        dash.append("  TARGET:   ", style=self.theme["text_primary"])
        dash.append(f"Row {self.selected_row}, Col {self.selected_col} / {self.cols}\n\n", style=self.theme["text_secondary"])

        # Selected process info
        dash.append("BUILDING INSPECT:\n", style="bold " + self.theme["text_secondary"])
        if selected_proc:
            name = selected_proc["name"]
            pid = selected_proc["pid"]
            p_cpu = selected_proc["cpu_percent"]
            p_mem_mb = selected_proc["memory_rss"] / (1024 * 1024)
            p_mem_pct = selected_proc["memory_percent"]
            threads = selected_proc.get("threads", 0)
            username = selected_proc.get("username", "N/A")
            cmdline = selected_proc.get("cmdline", name)
            
            # Identify district
            district_lbl = self._get_process_district(selected_proc).upper()

            dash.append(f"  NAME:    ", style=self.theme["text_primary"])
            dash.append(f"{name}\n", style="bold bright_white")
            dash.append(f"  PID:     ", style=self.theme["text_primary"])
            dash.append(f"{pid} ({district_lbl})\n", style=self.theme["text_secondary"])
            dash.append(f"  CPU %:   ", style=self.theme["text_primary"])
            dash.append(f"{p_cpu:.1f}%\n", style="bold bright_magenta")
            dash.append(f"  RAM RSS: ", style=self.theme["text_primary"])
            dash.append(f"{p_mem_mb:.1f} MB ({p_mem_pct:.1f}%)\n", style=self.theme["text_secondary"])
            dash.append(f"  THREADS: ", style=self.theme["text_primary"])
            dash.append(f"{threads}\n", style=self.theme["text_secondary"])
            dash.append(f"  USER:    ", style=self.theme["text_primary"])
            dash.append(f"{username}\n", style=self.theme["text_secondary"])
            
            if len(cmdline) > 30:
                cmdline = cmdline[:27] + "..."
            dash.append(f"  CMD:     ", style=self.theme["text_primary"])
            dash.append(f"{cmdline}\n\n", style="dim white")
        else:
            dash.append("  No building at targeted plot.\n", style="dim white")
            dash.append("  Use arrows or WASD to navigate grid.\n\n", style="dim white")

        # Controls Legend
        dash.append("CONTROLS:\n", style="bold " + self.theme["text_secondary"])
        dash.append("  [←↑↓→] [WASD]  : Navigate 2D Grid\n", style="dim white")
        dash.append("  [P]             : Toggle Helicopter Patrol\n", style="bold bright_cyan")
        dash.append("  [C] / [M]       : Sort by CPU / RAM\n", style="dim white")
        dash.append("  [F] / [Space]   : Filter / Pause TUI\n", style="dim white")
        dash.append("  [K] / [Delete]  : Kaiju Strike Demolition\n", style="bold bright_red")
        dash.append("  [O]             : Orbital Strike Demolition\n", style="bold bright_yellow")
        dash.append("  [Q] / [Esc]     : Shutdown Monitor\n", style="dim white")

        return Panel(
            Align.left(dash),
            border_style=self.theme["dashboard_border"],
            title="MATRIX DASHBOARD",
            title_align="center"
        )

    def _make_progress_bar(self, percentage: float, width: int = 10) -> str:
        """Helper to draw progress bars [████░░░░]"""
        filled = int((percentage / 100.0) * width)
        filled = max(0, min(width, filled))
        empty = width - filled
        return "[" + "█" * filled + "░" * empty + "]"

    def _format_speed(self, bytes_per_sec: float) -> str:
        """Format speeds (B/s, KB/s, MB/s)"""
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
