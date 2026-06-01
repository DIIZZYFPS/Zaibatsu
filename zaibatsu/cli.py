"""
CLI Entrypoint and Application Loop for Zaibatsu.
Coordinates input polling, metrics updates, and screen layout updates inside rich.live.Live.
"""

import sys
import time
import argparse
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from zaibatsu.config import THEMES, DEFAULT_THEME, DEFAULT_UPDATE_INTERVAL, MAX_BUILDINGS
from zaibatsu.monitor import SystemMonitor
from zaibatsu.renderer import CityRenderer
from zaibatsu.input import KeyboardInput
from zaibatsu.diff_engine import TUIRleDiffEngine

class ZaibatsuApp:
    def __init__(self, theme: str = DEFAULT_THEME, interval: float = DEFAULT_UPDATE_INTERVAL, demo: bool = False):
        self.console = Console()
        self.monitor = SystemMonitor()
        self.renderer = CityRenderer(theme_name=theme)
        self.keyboard = KeyboardInput()
        
        # State settings
        self.interval = interval
        self.sort_by = "cpu"  # cpu or memory
        self.search_query = ""
        self.is_paused = False
        self.running = False
        self.demo = demo
        
        # Filtering state
        self.filter_mode = False
        self.filter_input_buffer = ""

        # Helicopter states
        self.patrol_mode = False
        self.heli_x = 0
        self.heli_y = 0

        # Kaiju states
        self.kaiju_active = False
        self.kaiju_frame = 0.0
        self.kaiju_target_pid = 0
        self.kaiju_laser_ticks = 0.0
        self.kaiju_target_x = 0
        self.kaiju_target_y = 0
        self.kaiju_target_height = 0
        self.kaiju_target_width = 6
        self.kaiju_target_depth = 3
        
        # Grid slots for persistent building placement
        self.grid_slots: List[Optional[Dict[str, Any]]] = []

        # Highlighted process details caching (prevents slow WMI/SID calls in animation loops)
        self.last_selected_pid = -1
        self.selected_proc_details: Optional[Dict[str, Any]] = None

        # Process lifecycle tracking for event ticker
        self._prev_pid_set: set = set()
        self._prev_cpu_spikes: set = set()  # PIDs that were spiking last tick

        # Cached statistics to decoupled rendering frame rates from data polling rates
        self.cached_stats: Dict[str, Any] = {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "disk_read_speed": 0.0,
            "disk_write_speed": 0.0,
            "net_sent_speed": 0.0,
            "net_recv_speed": 0.0
        }
        self.cached_procs: List[Dict[str, Any]] = []
        self.last_stats_update = 0.0
        self.last_draw_time = 0.0

        # Orbital kinetic strike states
        self.orbital_active: bool = False
        self.orbital_frame: float = 0.0
        self.orbital_target_pid: int = 0
        self.orbital_target_x: int = -1
        self.orbital_target_y: int = -1
        self.orbital_target_height: int = 0
        self.orbital_target_width: int = 6
        self.orbital_target_depth: int = 3

    def _update_selected_proc_details(self, selected_proc: Optional[Dict[str, Any]]):
        """Fetch detailed stats only for the currently active/selected process."""
        if not selected_proc:
            self.last_selected_pid = -1
            self.selected_proc_details = None
            return
            
        pid = selected_proc["pid"]
        self.last_selected_pid = pid
        
        # Fetch CPU-heavy properties only once per selection/update cycle
        details = self.monitor.get_detailed_process_info(pid)
        
        # Combine base properties with the detailed metrics
        merged = selected_proc.copy()
        merged.update(details)
        self.selected_proc_details = merged

    def run(self):
        """Main application lifecycle runner."""
        # Terminal size verification
        # Rich console.size returns (width, height)
        term_width, term_height = self.console.size
        if term_height < 16 or term_width < 60:
            self.console.print("[bold red]Error: terminal window is too small for Zaibatsu.[/bold red]")
            self.console.print(f"Current size: {term_width}x{term_height}. Please resize to at least 60x16 and try again.")
            return

        self.running = True
        self.keyboard.start()
        
        # Start background metrics monitoring thread
        self.monitor.start(
            limit=MAX_BUILDINGS, 
            sort_by=self.sort_by, 
            search_query=self.search_query, 
            interval=self.interval,
            demo=self.demo
        )
        
        # Initialize UI layout — main content above, ticker strip below
        layout = Layout()
        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(name="ticker", size=1)
        )
        layout["main"].split_row(
            Layout(name="city", ratio=7),
            Layout(name="dashboard", ratio=3)
        )

        # Clear screen first to avoid terminal clutter
        self.console.clear()

        # Gather initial stats from cache
        self.cached_stats = self.monitor.get_system_stats()
        self.cached_procs = self.monitor.get_top_processes()
        self.last_stats_update = self.monitor.last_update_time
        
        # Initialize grid slots
        self._update_grid_slots()

        # Seed the event ticker so it has content from the start
        self.renderer.add_event("ZAIBATSU CITY MONITOR ONLINE")
        self.renderer.add_event(f"TRACKING {len(self.cached_procs)} PROCESSES")
        
        # Initialize selection details
        active_procs = self._get_active_processes()
        idx = self.renderer.selected_row * self.renderer.cols + self.renderer.selected_col
        selected = active_procs[idx] if idx < len(active_procs) else None
        self._update_selected_proc_details(selected)

        # Initialize Double-Buffer TUI Diff Engine
        self.diff_engine = TUIRleDiffEngine(self.console)
        self.diff_engine.reset()
        self.last_draw_time = time.time()

        # Active rendering loop
        try:
            while self.running:
                # Calculate dt for frame-rate independent animations
                current_time = time.time()
                dt = current_time - self.last_draw_time
                self.last_draw_time = current_time
                dt = max(0.001, dt)

                # 1. Process User Inputs
                self._handle_inputs()
                
                # 2. Update stats and process list from the background thread's cache if new metrics are ready
                monitor_last_update = self.monitor.last_update_time
                if not self.is_paused and (monitor_last_update > self.last_stats_update):
                    self.cached_stats = self.monitor.get_system_stats()
                    self.cached_procs = self.monitor.get_top_processes()
                    self.last_stats_update = monitor_last_update
                    
                    self._update_grid_slots()
                    
                    # Detect process lifecycle events for the scrolling ticker
                    self._detect_process_events()
                    
                    # Refresh details for selected process after stats reload
                    active_procs = self._get_active_processes()
                    idx = self.renderer.selected_row * self.renderer.cols + self.renderer.selected_col
                    selected = active_procs[idx] if idx < len(active_procs) else None
                    self._update_selected_proc_details(selected)

                # Only re-sync grid slots on resize (rows/cols changed)
                new_limit = self.renderer.rows * self.renderer.cols
                if new_limit != len(self.grid_slots):
                    self._update_grid_slots()

                # Update helicopter selection if active
                if self.patrol_mode:
                    self._update_helicopter_selection()

                # Kaiju State update
                if self.kaiju_active:
                    self.kaiju_frame += dt / 0.1
                    
                    target_x = self.kaiju_target_x
                    target_y = self.kaiju_target_y
                    target_height = self.kaiju_target_height
                    target_width = self.kaiju_target_width
                    target_depth = self.kaiju_target_depth
                    
                    target_proc = None
                    for p in self.cached_procs:
                        if p["pid"] == self.kaiju_target_pid:
                            target_proc = p
                            break
                    if not target_proc:
                        target_proc = {"pid": self.kaiju_target_pid, "name": "Process"}

                    stop_x = max(1, target_x - 8)
                    kx = min(stop_x, int(self.kaiju_frame) * 6)
                    
                    if kx == stop_x:
                        prev_ticks = int(self.kaiju_laser_ticks)
                        self.kaiju_laser_ticks += dt / 0.1
                        curr_ticks = int(self.kaiju_laser_ticks)
                        if prev_ticks < 5 <= curr_ticks:
                            # Trigger collapse and termination
                            self.renderer.start_demolition(target_proc, (target_x, target_y, target_height, target_width, target_depth))
                            self.monitor.terminate_process(self.kaiju_target_pid)
                        elif curr_ticks > 5 + 6: # stand for collapse duration (6 frames)
                            # Deactivate Kaiju
                            self.kaiju_active = False
                            self.kaiju_frame = 0.0
                            self.kaiju_laser_ticks = 0.0

                # Orbital State update
                if self.orbital_active:
                    prev_orbital_frame = int(self.orbital_frame)
                    self.orbital_frame += dt / 0.1
                    curr_orbital_frame = int(self.orbital_frame)
                    
                    if curr_orbital_frame == 6 and prev_orbital_frame < 6:
                        target_proc = None
                        for p in self.cached_procs:
                            if p["pid"] == self.orbital_target_pid:
                                target_proc = p
                                break
                        if not target_proc:
                            target_proc = {"pid": self.orbital_target_pid, "name": "Process"}
                            
                        # Instantiate 3D demolition tracking on the target cell
                        self.renderer.start_demolition(
                            target_proc, 
                            (self.orbital_target_x, self.orbital_target_y, 
                             self.orbital_target_height, self.orbital_target_width, self.orbital_target_depth)
                        )
                        # Non-blocking kill hand-off execution
                        self.monitor.terminate_process(self.orbital_target_pid)
                        
                    elif curr_orbital_frame > 9:
                        self.orbital_active = False
                        self.orbital_frame = 0.0

                # 3. Handle Demolitions and Selection boundaries
                cols_count = self.renderer.cols
                self.renderer.selected_col = min(self.renderer.selected_col, cols_count - 1)
                
                active_procs = self._get_active_processes()
                idx = self.renderer.selected_row * cols_count + self.renderer.selected_col
                selected_proc = active_procs[idx] if idx < len(active_procs) else None

                # If selection index has changed, update details immediately
                if selected_proc and selected_proc["pid"] != self.last_selected_pid:
                    self._update_selected_proc_details(selected_proc)
                elif not selected_proc:
                    self._update_selected_proc_details(None)

                # 4. Generate & Draw Canvas Frames
                term_w, term_h = self.console.size
                city_w = int(term_w * 0.7) - 2 # account for layout splits and border margin
                city_h = term_h - 5  # subtract 5: 2 Panel borders + 2 Layout splits + 1 ticker strip
                
                city_renderable = self.renderer.render_city(
                    width=city_w,
                    height=city_h,
                    processes=self.grid_slots,
                    system_stats=self.cached_stats,
                    sort_by=self.sort_by,
                    search_query=self.search_query,
                    patrol_mode=self.patrol_mode,
                    heli_coords=(self.heli_x, self.heli_y),
                    kaiju_active=self.kaiju_active,
                    kaiju_frame=int(self.kaiju_frame),
                    kaiju_target_pid=self.kaiju_target_pid,
                    kaiju_target_x=self.kaiju_target_x,
                    kaiju_target_y=self.kaiju_target_y,
                    orbital_active=self.orbital_active,
                    orbital_frame=int(self.orbital_frame),
                    orbital_target_x=self.orbital_target_x,
                    orbital_target_y=self.orbital_target_y,
                    orbital_target_width=self.orbital_target_width,
                    dt=dt
                )
                
                # Check if dynamic grid size changed and update monitor limit
                expected_limit = self.renderer.rows * self.renderer.cols
                if self.monitor.limit != expected_limit:
                    self.monitor.trigger_immediate_update(self.sort_by, self.search_query, limit=expected_limit)
                
                # Build sidebar stats dashboard using cached selection details
                dash_renderable = self.renderer.draw_dashboard(
                    system_stats=self.cached_stats,
                    selected_proc=self.selected_proc_details,
                    sort_by=self.sort_by,
                    search_query=self.search_query,
                    is_paused=self.is_paused,
                    is_demo=self.demo
                )
                
                # Update layout panels
                layout["city"].update(Panel(city_renderable, border_style=self.renderer.theme["building_border"], title="ZAIBATSU DISTRICT"))
                layout["dashboard"].update(dash_renderable)
                
                # Update the scrolling event ticker bar
                ticker_renderable = self.renderer.build_ticker_bar(term_w)
                layout["ticker"].update(ticker_renderable)
                
                # Draw layout using RLE Diff Engine
                self.diff_engine.draw(layout)

                # We run at 20 FPS (50ms ticks) for smooth scrolling animations
                time.sleep(0.05)

        except KeyboardInterrupt:
            pass
        finally:
            self.monitor.stop()
            self.keyboard.stop()
            self.diff_engine.shutdown()
            self.console.print("[bold bright_magenta]Zaibatsu system shutdown completed gracefully. Goodbye.[/bold bright_magenta]")

    def _get_active_processes(self) -> List[Optional[Dict[str, Any]]]:
        """Returns processes currently in the grid (replacing ones in demolition with None)."""
        demolishing_pids = set(self.renderer.demolitions.keys())
        return [p if (p and p["pid"] not in demolishing_pids) else None for p in self.grid_slots]

    def _update_grid_slots(self):
        """Update grid slots to keep process building positions persistent."""
        expected_limit = self.renderer.rows * self.renderer.cols
        
        # 1. Adjust slots list size if limit changed
        if len(self.grid_slots) < expected_limit:
            self.grid_slots.extend([None] * (expected_limit - len(self.grid_slots)))
        elif len(self.grid_slots) > expected_limit:
            self.grid_slots = self.grid_slots[:expected_limit]
            
        # 2. Extract set of PIDs in the incoming top processes
        incoming_procs = {p["pid"]: p for p in self.cached_procs}
        
        # 3. Retain existing processes that are still in top processes
        active_pids = set()
        for i in range(len(self.grid_slots)):
            slot = self.grid_slots[i]
            if slot and slot["pid"] in incoming_procs:
                # Update details in-place
                self.grid_slots[i] = incoming_procs[slot["pid"]].copy()
                active_pids.add(slot["pid"])
            else:
                self.grid_slots[i] = None # clear vacant slot
                
        # 4. Fill vacant slots with new incoming processes
        for p in self.cached_procs:
            if p["pid"] not in active_pids:
                # Find first vacant slot
                for i in range(len(self.grid_slots)):
                    if self.grid_slots[i] is None:
                        self.grid_slots[i] = p.copy()
                        active_pids.add(p["pid"])
                        break

    def _handle_inputs(self):
        """Read and execute keyboard events from queue."""
        while True:
            key = self.keyboard.get_key()
            if not key:
                break
            
            # If Kaiju or Orbital mode is active, lock standard controls except emergency exit
            if self.kaiju_active or self.orbital_active:
                if key in ('q', 'escape'):
                    self.running = False
                continue
                
            cols_count = self.renderer.cols
            rows_count = self.renderer.rows
            term_w, term_h = self.console.size
            
            # --- FILTER/SEARCH MODE KEY HANDLING ---
            if self.filter_mode:
                if key == 'escape':
                    self.filter_mode = False
                    self.filter_input_buffer = ""
                    # Restore previous search
                elif key == 'enter':
                    self.filter_mode = False
                    self.search_query = self.filter_input_buffer
                    self.renderer.selected_row = rows_count - 1
                    self.renderer.selected_col = 0
                    # Trigger immediate background reload with the filter applied
                    self.monitor.trigger_immediate_update(self.sort_by, self.search_query)
                elif key == 'backspace':
                    self.filter_input_buffer = self.filter_input_buffer[:-1]
                    self.search_query = self.filter_input_buffer
                    self.monitor.trigger_immediate_update(self.sort_by, self.search_query)
                elif len(key) == 1:
                    self.filter_input_buffer += key
                    self.search_query = self.filter_input_buffer
                    self.monitor.trigger_immediate_update(self.sort_by, self.search_query)
                continue

            # --- STANDARD NAVIGATION KEY HANDLING ---
            if key in ('q', 'escape'):
                self.running = False
            elif key == 'space':
                self.is_paused = not self.is_paused
            elif key == 'c':
                self.sort_by = "cpu"
                self.renderer.selected_row = rows_count - 1
                self.renderer.selected_col = 0
                self.monitor.trigger_immediate_update(self.sort_by, self.search_query)
            elif key == 'm':
                self.sort_by = "memory"
                self.renderer.selected_row = rows_count - 1
                self.renderer.selected_col = 0
                self.monitor.trigger_immediate_update(self.sort_by, self.search_query)
            elif key == 'f':
                self.filter_mode = True
                self.filter_input_buffer = ""
            elif key in ('left', 'a'):
                if self.patrol_mode:
                    self.heli_x = max(0, self.heli_x - 2)
                    self._update_helicopter_selection()
                else:
                    self.renderer.selected_col = (self.renderer.selected_col - 1) % cols_count
            elif key in ('right', 'd'):
                if self.patrol_mode:
                    self.heli_x = min(term_w - 22, self.heli_x + 2)
                    self._update_helicopter_selection()
                else:
                    self.renderer.selected_col = (self.renderer.selected_col + 1) % cols_count
            elif key in ('up', 'w'):
                if self.patrol_mode:
                    self.heli_y = max(0, self.heli_y - 1)
                    self._update_helicopter_selection()
                else:
                    self.renderer.selected_row = (self.renderer.selected_row - 1) % rows_count
            elif key in ('down', 's'):
                if self.patrol_mode:
                    self.heli_y = min(term_h - 6, self.heli_y + 1)
                    self._update_helicopter_selection()
                else:
                    self.renderer.selected_row = (self.renderer.selected_row + 1) % rows_count
            elif key == 'p':
                self.patrol_mode = not self.patrol_mode
                if self.patrol_mode:
                    # Initialize helicopter position above current selection
                    self.heli_y = 2
                    hx = term_w // 2 - 5
                    if hasattr(self.renderer, "last_building_positions") and self.renderer.last_building_positions:
                        for r_idx, c_idx, col_start, ground_y, b_height, b_width, b_depth, proc in self.renderer.last_building_positions:
                            if r_idx == self.renderer.selected_row and c_idx == self.renderer.selected_col:
                                hx = col_start - 2
                                break
                    self.heli_x = max(0, min(term_w - 22, hx))
                    self._update_helicopter_selection()
            elif key in ('k', 'delete'):
                if not self.kaiju_active:
                    self._trigger_kaiju_demolition()
            elif key == 'o':
                if not self.orbital_active and not self.kaiju_active:
                    self._trigger_orbital_strike()

    def _update_helicopter_selection(self):
        """Update selected building row/col based on current helicopter coordinates."""
        if not hasattr(self.renderer, "last_building_positions") or not self.renderer.last_building_positions:
            return
            
        best_r = self.renderer.selected_row
        best_c = self.renderer.selected_col
        min_dist = float('inf')
        
        # Center of helicopter searchlight
        hx = self.heli_x + 5
        hy = self.heli_y
        
        for r_idx, c_idx, col_start, ground_y, b_height, b_width, b_depth, proc in self.renderer.last_building_positions:
            bx = col_start + b_width // 2
            by = ground_y - b_height // 2
            
            # Weighted distance: prioritize horizontal alignment, but vertical matches rows
            dist = (bx - hx) ** 2 + ((by - hy) * 2) ** 2
            if dist < min_dist:
                min_dist = dist
                best_r = r_idx
                best_c = c_idx
                
        self.renderer.selected_row = best_r
        self.renderer.selected_col = best_c

    def _trigger_kaiju_demolition(self):
        """Prepares and starts the Kaiju demolition sequence."""
        active_procs = self._get_active_processes()
        cols_count = self.renderer.cols
        idx = self.renderer.selected_row * cols_count + self.renderer.selected_col
        if idx >= len(active_procs):
            return
            
        target_proc = active_procs[idx]
        if not target_proc:
            return  # empty grid slot — nothing to demolish
        self.kaiju_target_pid = target_proc["pid"]
        
        # Cache targeted building's layout coordinates and dimensions
        self.kaiju_target_x = -1
        self.kaiju_target_y = -1
        self.kaiju_target_height = -1
        self.kaiju_target_width = 6
        self.kaiju_target_depth = 3
        if hasattr(self.renderer, "last_building_positions"):
            for r, c, col_start, ground_y, b_height, b_width, b_depth, proc in self.renderer.last_building_positions:
                if proc["pid"] == self.kaiju_target_pid:
                    self.kaiju_target_x = col_start
                    self.kaiju_target_y = ground_y
                    self.kaiju_target_height = b_height
                    self.kaiju_target_width = b_width
                    self.kaiju_target_depth = b_depth
                    break
                    
        if self.kaiju_target_x == -1:
            term_w, term_h = self.console.size
            self.kaiju_target_x = int(term_w * 0.3)
            self.kaiju_target_y = term_h - 3
            self.kaiju_target_height = 6
            self.kaiju_target_width = 6
            self.kaiju_target_depth = 3

        self.kaiju_active = True
        self.kaiju_frame = 0
        self.kaiju_laser_ticks = 0

    def _trigger_orbital_strike(self):
        """Locates targeting assets and initiates the satellite kinetic sequence."""
        import os
        active_procs = self._get_active_processes()
        cols_count = self.renderer.cols
        idx = self.renderer.selected_row * cols_count + self.renderer.selected_col
        if idx >= len(active_procs):
            return
            
        target_proc = active_procs[idx]
        if not target_proc:
            return
            
        # Hard Security Boundary Check: Prevent self-destruction terminal corruption
        if target_proc["pid"] == os.getpid():
            self.renderer.add_event("WIRE: ERROR - MAINFRAME SELF-TARGET BLOCK")
            return

        self.orbital_target_pid = target_proc["pid"]
        self.orbital_target_x = -1
        
        # Extract structural layout geometry from positions cache
        if hasattr(self.renderer, "last_building_positions"):
            for r, c, col_start, ground_y, b_height, b_width, b_depth, proc in self.renderer.last_building_positions:
                if proc["pid"] == self.orbital_target_pid:
                    self.orbital_target_x = col_start
                    self.orbital_target_y = ground_y
                    self.orbital_target_height = b_height
                    self.orbital_target_width = b_width
                    self.orbital_target_depth = b_depth
                    break

        if self.orbital_target_x == -1:
            return # Abort if target coordinates drop out of cache bounds
            
        self.orbital_active = True
        self.orbital_frame = 0
        self.renderer.add_event(f"BAT: SATELLITE KINETIC LOCK ON PID {self.orbital_target_pid}")

    def _detect_process_events(self):
        """Detect process spawns, deaths, and CPU spikes to feed the event ticker."""
        current_pids = {p["pid"]: p for p in self.cached_procs}
        current_pid_set = set(current_pids.keys())

        # Spawns (new PIDs not seen before)
        if self._prev_pid_set:  # Skip first tick
            spawned = current_pid_set - self._prev_pid_set
            for pid in spawned:
                name = current_pids[pid]["name"]
                self.renderer.add_event(f">> {name} SPAWNED [PID:{pid}]")

            # Deaths (PIDs that disappeared)
            died = self._prev_pid_set - current_pid_set
            for pid in died:
                self.renderer.add_event(f"xx PROCESS EXITED [PID:{pid}]")

        # CPU spikes (>80% and wasn't spiking before)
        new_spikes = set()
        for pid, proc in current_pids.items():
            if proc["cpu_percent"] > 80:
                new_spikes.add(pid)
                if pid not in self._prev_cpu_spikes:
                    self.renderer.add_event(f"!! {proc['name']} CPU SPIKE {proc['cpu_percent']:.0f}%")

        self._prev_pid_set = current_pid_set
        self._prev_cpu_spikes = new_spikes


def main():
    parser = argparse.ArgumentParser(
        description="Zaibatsu: A retro-cyberpunk terminal cityscape process monitor."
    )
    parser.add_argument(
        "-t", "--theme",
        choices=list(THEMES.keys()),
        default=DEFAULT_THEME,
        help="Visual theme (default: cyberpunk)"
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=DEFAULT_UPDATE_INTERVAL,
        help="Update interval for metrics in seconds (default: 0.5)"
    )
    parser.add_argument(
        "-d", "--demo",
        action="store_true",
        help="Run in Demo Mode with mock processes and safe terminations"
    )
    args = parser.parse_args()

    app = ZaibatsuApp(theme=args.theme, interval=args.interval, demo=args.demo)
    app.run()

if __name__ == "__main__":
    main()
