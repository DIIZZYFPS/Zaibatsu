# 🌆 Zaibatsu Cityscape Process Monitor

Zaibatsu is an interactive, retro-cyberpunk terminal-based process monitor that represents running system processes as a living city skyline. The height, density, and animation of the buildings directly reflect how active and full your computer is.

---

## 🎨 Visual Features

- **The Skyline (Processes)**: Each building represents a running process.
  - **Height**: Proportional to the resource usage of the process (CPU % or Memory RSS).
  - **Windows**: The density of lit windows and their blinking speed represent real-time CPU usage.
  - **Top Chimneys**: Processes with high Disk I/O activity will release smoke or steam particles rising from their roofs.
  - **Neon Signs**: The names of the processes are printed vertically down the center of the buildings.
- **The Sky (System Load)**:
  - **Stars**: Twinkle dynamically.
  - **Moon**: Displays phases (Crescent, Half, Gibbous, Full) and warning colors based on overall RAM consumption.
  - **Clouds**: Scroll horizontally with speeds mapped to background activity.
  - **Lightning**: Flashes across the sky when system-wide CPU load exceeds 80%.
- **The Street (I/O Traffic)**:
  - Cars drive across the bottom lanes of the city.
  - Car spawn rate and driving speed are mapped to overall Disk Read/Write and Network speeds.
- **The Dashboard (TUI Control Panel)**:
  - Shows real-time CPU and RAM progress bars.
  - Displays Disk and Network speeds in B/s, KB/s, or MB/s.
  - Displays full detail statistics of the currently highlighted building/process.
  - Displays a terminal text filter/search bar.

---

## 🎮 Keyboard Controls

| Key | Action |
| --- | --- |
| `←` / `→` / `↑` / `↓` or `W` / `A` / `S` / `D` | Target/Highlight a building in the 2D grid |
| `C` | Sort city buildings by **CPU usage** |
| `M` | Sort city buildings by **Memory usage** |
| `F` | Open process name filter (type query, press `Enter` to apply, `Esc` to cancel) |
| `Space` | Pause / Resume real-time metrics updates (city animations stay active) |
| `K` / `Delete` | **Demolish Building** — terminates the selected process with an explosion and collapse animation! |
| `Q` / `Esc` | Shutdown Zaibatsu monitor |

---

## 🚀 Setup & Launch

Zaibatsu runs on Windows (using Python's native `msvcrt` for keyboard polling) and requires a terminal that supports Unicode box characters and ANSI colors (e.g. Windows Terminal, VS Code, PowerShell, command prompt).

### 1. Setup Virtual Environment
Initialize a Python virtual environment and install dependencies:
```powershell
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Zaibatsu
Run the launcher:
```powershell
python run.py
```

### 3. Customize Options
You can configure themes (`cyberpunk`, `matrix`, `sunset`) and refresh rates:
```powershell
python run.py --theme matrix --interval 0.2
```

---

## 🛠️ Project Structure

- [run.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/run.py): CLI launcher script.
- [zaibatsu/cli.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/zaibatsu/cli.py): Main terminal screen layout controller.
- [zaibatsu/renderer.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/zaibatsu/renderer.py): Cityscape layout drawing logic and animations.
- [zaibatsu/monitor.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/zaibatsu/monitor.py): System and process stats gathering using `psutil`.
- [zaibatsu/input.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/zaibatsu/input.py): Non-blocking keyboard event listening queue.
- [zaibatsu/config.py](file:///c:/Users/DIIZZY/Documents/Code/Light%20Projects/Zaibatsu/zaibatsu/config.py): Theme declarations and scaling parameters.
