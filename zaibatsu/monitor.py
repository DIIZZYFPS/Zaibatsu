"""
System and process monitoring utilizing psutil.
Queries process statistics in a background thread to prevent UI lag.
"""

import time
import psutil
import threading
from typing import Dict, List, Any, Optional

class SystemMonitor:
    def __init__(self):
        # Thread safety & control
        self.lock = threading.Lock()
        self.update_event = threading.Event()
        self.running = False
        self.thread = None
        self.last_update_time = 0.0

        # Latest gathered metrics cache
        self.system_stats: Dict[str, Any] = {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "disk_read_speed": 0.0,
            "disk_write_speed": 0.0,
            "net_sent_speed": 0.0,
            "net_recv_speed": 0.0
        }
        self.top_processes: List[Dict[str, Any]] = []
        
        # Thread parameters
        self.limit = 12
        self.sort_by = "cpu"
        self.search_query = ""
        self.interval = 0.5

        # Demo mode state
        self.demo = False
        self._demo_processes: List[Dict[str, Any]] = []
        self._demo_cpu = 80.0
        self._demo_ram = 70.0

        # Historical metrics for rate calculation (Disk and Network)
        self.prev_time = time.time()
        
        # Disk IO
        try:
            disk = psutil.disk_io_counters()
            self.prev_disk_read = disk.read_bytes
            self.prev_disk_write = disk.write_bytes
        except Exception:
            self.prev_disk_read = 0
            self.prev_disk_write = 0
            
        # Net IO
        try:
            net = psutil.net_io_counters()
            self.prev_net_sent = net.bytes_sent
            self.prev_net_recv = net.bytes_recv
        except Exception:
            self.prev_net_sent = 0
            self.prev_net_recv = 0

    def start(self, limit: int = 12, sort_by: str = "cpu", search_query: str = "", interval: float = 0.5, demo: bool = False):
        """Start the background metrics gathering thread."""
        with self.lock:
            self.limit = limit
            self.sort_by = sort_by
            self.search_query = search_query
            self.interval = interval
            self.demo = demo
            if self.running:
                return
            self.running = True
            self.update_event.clear()
            
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the background metrics thread."""
        with self.lock:
            self.running = False
        self.update_event.set() # wake up if sleeping
        if self.thread:
            self.thread.join(timeout=1.0)

    def trigger_immediate_update(self, sort_by: str, search_query: str, limit: Optional[int] = None):
        """Update monitor parameters and wake background thread for an immediate query cycle."""
        with self.lock:
            self.sort_by = sort_by
            self.search_query = search_query
            if limit is not None:
                self.limit = limit
        self.update_event.set()

    def get_system_stats(self) -> Dict[str, Any]:
        """Thread-safe retrieval of latest system stats."""
        with self.lock:
            return self.system_stats.copy()

    def get_top_processes(self) -> List[Dict[str, Any]]:
        """Thread-safe retrieval of latest top processes."""
        with self.lock:
            return [p.copy() for p in self.top_processes]

    def _monitor_loop(self):
        """Background thread target that loops and updates stats."""
        try:
            self._update_metrics()
        except Exception:
            pass

        while True:
            # Check running state
            with self.lock:
                if not self.running:
                    break
                interval = self.interval
            
            # Wait until interval elapsed or event is set (config change / force refresh)
            woken = self.update_event.wait(timeout=interval)
            
            with self.lock:
                if not self.running:
                    break
            
            # Clear event in case it was set
            self.update_event.clear()
            
            try:
                self._update_metrics()
            except Exception:
                pass

    def _update_demo_metrics(self):
        """Simulate system and process metrics for Demo Mode."""
        import random
        if not self._demo_processes:
            names = [
                "ice_breaker.exe", "net_daemon", "neural_link", "corp_drone.exe", 
                "relic_parser", "matrix_stabilizer", "ai_core_01", "shodan_sub",
                "deck_runner.exe", "black_ice", "grid_firewall", "synth_driver",
                "cyber_net.exe", "chrome_socket", "neon_pulse", "data_siphon",
                "hologram_host", "reaper_worm", "quantum_enc", "nanite_sync"
            ]
            usernames = ["deck_jockey", "root", "corp_admin", "neon_rider", "system"]
            for i, name in enumerate(names):
                pid = random.randint(1000, 9999)
                cpu = random.uniform(0.5, 45.0) if i < 8 else random.uniform(0.0, 5.0)
                rss = random.randint(20 * 1024 * 1024, 4 * 1024 * 1024 * 1024)
                threads = random.randint(1, 32)
                username = random.choice(usernames)
                cmdline = f"/bin/{name.split('.')[0]} --listen --port {random.randint(1024, 65535)}" if random.random() > 0.3 else f"C:\\Zaibatsu\\Bin\\{name}"
                self._demo_processes.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu,
                    "memory_rss": rss,
                    "memory_percent": (rss / (32 * 1024**3)) * 100.0,
                    "io_activity": random.uniform(0, 10 * 1024**2),
                    "threads": threads,
                    "username": username,
                    "cmdline": cmdline,
                    "create_time": time.time() - random.randint(3600, 86400)
                })

        # Dynamic Lifecycle
        if random.random() < 0.05 and len(self._demo_processes) < 30:
            names = [
                "ice_breaker.exe", "net_daemon", "neural_link", "corp_drone.exe", 
                "relic_parser", "matrix_stabilizer", "ai_core_01", "shodan_sub",
                "deck_runner.exe", "black_ice", "grid_firewall", "synth_driver",
                "cyber_net.exe", "chrome_socket", "neon_pulse", "data_siphon",
                "hologram_host", "reaper_worm", "quantum_enc", "nanite_sync"
            ]
            name = random.choice(names)
            usernames = ["deck_jockey", "root", "corp_admin", "neon_rider", "system"]
            pid = random.randint(1000, 9999)
            existing_pids = {p["pid"] for p in self._demo_processes}
            while pid in existing_pids:
                pid = random.randint(1000, 9999)
            
            rss = random.randint(20 * 1024 * 1024, int(1.5 * 1024 * 1024 * 1024))
            p = {
                "pid": pid,
                "name": name,
                "cpu_percent": random.uniform(0.1, 10.0),
                "memory_rss": rss,
                "memory_percent": (rss / (32 * 1024**3)) * 100.0,
                "io_activity": random.uniform(0, 1 * 1024**2),
                "threads": random.randint(1, 8),
                "username": random.choice(usernames),
                "cmdline": f"/bin/{name.split('.')[0]}",
                "create_time": time.time()
            }
            self._demo_processes.append(p)

        elif random.random() < 0.03 and len(self._demo_processes) > 10:
            low_cpu_procs = [p for p in self._demo_processes if p["cpu_percent"] < 2.0]
            if low_cpu_procs:
                p_to_remove = random.choice(low_cpu_procs)
                self._demo_processes.remove(p_to_remove)

        # Fluctuate existing
        for p in self._demo_processes:
            delta_cpu = random.uniform(-5.0, 5.0)
            p["cpu_percent"] = max(0.0, min(99.0, p["cpu_percent"] + delta_cpu))
            delta_rss = random.randint(-50 * 1024 * 1024, 50 * 1024 * 1024)
            p["memory_rss"] = max(10 * 1024 * 1024, p["memory_rss"] + delta_rss)
            p["memory_percent"] = (p["memory_rss"] / (32 * 1024**3)) * 100.0
            p["io_activity"] = max(0.0, p["io_activity"] + random.uniform(-1 * 1024**2, 1 * 1024**2))

        # Filter & Sort
        with self.lock:
            sort_by = self.sort_by
            search_query = self.search_query
            limit = self.limit

        filtered = []
        search_query_lower = search_query.lower()
        for p in self._demo_processes:
            if search_query_lower and search_query_lower not in p["name"].lower():
                continue
            filtered.append(p.copy())

        if sort_by == "cpu":
            filtered.sort(key=lambda x: x["cpu_percent"], reverse=True)
        else:
            filtered.sort(key=lambda x: x["memory_rss"], reverse=True)

        top_processes = filtered[:limit]

        # Stats
        self._demo_cpu = max(70.0, min(95.0, self._demo_cpu + random.uniform(-3.0, 3.0)))
        self._demo_ram = max(60.0, min(90.0, self._demo_ram + random.uniform(-1.0, 1.0)))

        disk_r = random.uniform(0.1, 5.0) * 1024**2
        disk_w = random.uniform(0.1, 2.0) * 1024**2
        net_s = random.uniform(0.05, 1.0) * 1024**2
        net_r = random.uniform(0.1, 8.0) * 1024**2

        new_system_stats = {
            "cpu_percent": self._demo_cpu,
            "ram_percent": self._demo_ram,
            "ram_used_gb": 32.0 * (self._demo_ram / 100.0),
            "ram_total_gb": 32.0,
            "disk_read_speed": disk_r,
            "disk_write_speed": disk_w,
            "net_sent_speed": net_s,
            "net_recv_speed": net_r,
        }

        with self.lock:
            self.system_stats = new_system_stats
            self.top_processes = top_processes
            self.last_update_time = time.time()

    def _update_metrics(self):
        """Perform the psutil system calls and update local state cache."""
        with self.lock:
            is_demo = self.demo
        if is_demo:
            self._update_demo_metrics()
            return

        current_time = time.time()
        elapsed = current_time - self.prev_time
        
        disk_read_speed = 0.0
        disk_write_speed = 0.0
        net_sent_speed = 0.0
        net_recv_speed = 0.0

        if elapsed > 0.01:
            try:
                disk = psutil.disk_io_counters()
                read_diff = max(0, disk.read_bytes - self.prev_disk_read)
                write_diff = max(0, disk.write_bytes - self.prev_disk_write)
                disk_read_speed = read_diff / elapsed
                disk_write_speed = write_diff / elapsed
                self.prev_disk_read = disk.read_bytes
                self.prev_disk_write = disk.write_bytes
            except Exception:
                pass

            try:
                net = psutil.net_io_counters()
                sent_diff = max(0, net.bytes_sent - self.prev_net_sent)
                recv_diff = max(0, net.bytes_recv - self.prev_net_recv)
                net_sent_speed = sent_diff / elapsed
                net_recv_speed = recv_diff / elapsed
                self.prev_net_sent = net.bytes_sent
                self.prev_net_recv = net.bytes_recv
            except Exception:
                pass
                
            self.prev_time = current_time

        cpu_percent = psutil.cpu_percent(interval=None)
        virtual_mem = psutil.virtual_memory()

        new_system_stats = {
            "cpu_percent": cpu_percent,
            "ram_percent": virtual_mem.percent,
            "ram_used_gb": virtual_mem.used / (1024**3),
            "ram_total_gb": virtual_mem.total / (1024**3),
            "disk_read_speed": disk_read_speed,
            "disk_write_speed": disk_write_speed,
            "net_sent_speed": net_sent_speed,
            "net_recv_speed": net_recv_speed,
        }

        # Gather target configs
        with self.lock:
            sort_by = self.sort_by
            search_query = self.search_query
            limit = self.limit

        processes_data = []
        search_query_lower = search_query.lower()
        cores = psutil.cpu_count() or 1

        # Query process table directly using process_iter (C-level iteration yields massive speedup)
        for p in psutil.process_iter(attrs=['pid', 'name', 'cpu_percent', 'memory_info', 'memory_percent']):
            try:
                pid = p.info['pid'] or p.pid
                if pid == 0:
                    continue
                
                name = p.info['name']
                if not name:
                    name = f"Process {pid}"
                
                # Apply filter early if specified
                if search_query_lower and search_query_lower not in name.lower():
                    continue

                cpu_pct = p.info['cpu_percent']
                if cpu_pct is None:
                    cpu_pct = 0.0
                normalized_cpu = cpu_pct / cores

                mem_info = p.info['memory_info']
                rss = mem_info.rss if mem_info else 0
                mem_pct = p.info['memory_percent'] or 0.0

                processes_data.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": normalized_cpu,  # Normalized to [0 - 100]
                    "raw_cpu_percent": cpu_pct,     # Standard [0 - cores*100]
                    "memory_rss": rss,
                    "memory_percent": mem_pct,
                    "io_activity": 0.0,
                    "_proc_ref": p  # Stash handle for IO/thread enrichment (avoids re-instantiation)
                })

            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, AttributeError):
                continue

        # Sort the filtered list
        if sort_by == "cpu":
            processes_data.sort(key=lambda x: x["cpu_percent"], reverse=True)
        else: # memory
            processes_data.sort(key=lambda x: x["memory_rss"], reverse=True)

        top_processes = processes_data[:limit]

        # Gather IO stats, thread count, and username only for top visible processes
        # Reuse the stashed Process handle from process_iter instead of creating new ones
        for proc in top_processes:
            pid = proc["pid"]
            proc["threads"] = 1
            proc["username"] = ""
            p = proc.pop("_proc_ref", None)
            if not p:
                continue
            try:
                # IO activity
                try:
                    io_cnt = p.io_counters()
                    proc["io_activity"] = io_cnt.read_bytes + io_cnt.write_bytes
                except Exception:
                    pass
                # Threads count
                try:
                    proc["threads"] = p.num_threads()
                except Exception:
                    pass
                # Username (needed for district classification on all platforms)
                try:
                    proc["username"] = p.username()
                except Exception:
                    pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass

        # Drop _proc_ref from non-top processes (they won't be cached)
        # (Already popped from top_processes above; remaining entries in processes_data
        #  are not stored, so no cleanup needed)

        # Write updates back to cache variables under lock
        with self.lock:
            self.system_stats = new_system_stats
            self.top_processes = top_processes
            self.last_update_time = time.time()

    def get_detailed_process_info(self, pid: int) -> Dict[str, Any]:
        """Fetch detailed stats for a single process (the highlighted one)."""
        with self.lock:
            is_demo = self.demo
        if is_demo:
            for p in self._demo_processes:
                if p["pid"] == pid:
                    return {
                        "cmdline": p["cmdline"],
                        "username": p["username"],
                        "threads": p["threads"],
                        "create_time": p["create_time"]
                    }
            return {
                "cmdline": "",
                "username": "N/A",
                "threads": 0,
                "create_time": 0.0
            }

        info = {
            "cmdline": "",
            "username": "N/A",
            "threads": 0,
            "create_time": 0.0
        }
        try:
            p = psutil.Process(pid)
            # cmdline
            cmdline = []
            try:
                cmdline = p.cmdline()
            except psutil.AccessDenied:
                pass
            info["cmdline"] = " ".join(cmdline) if cmdline else p.name()

            # username
            username = ""
            try:
                username = p.username()
            except psutil.AccessDenied:
                pass
            if username:
                info["username"] = username

            # num_threads
            threads = 0
            try:
                threads = p.num_threads()
            except (psutil.AccessDenied, AttributeError):
                pass
            info["threads"] = threads

            # create_time
            create_time = 0.0
            try:
                create_time = p.create_time()
            except psutil.AccessDenied:
                pass
            info["create_time"] = create_time

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
        return info

    def terminate_process(self, pid: int) -> bool:
        """Attempt to terminate a process asynchronously to prevent main loop stuttering."""
        import threading
        with self.lock:
            is_demo = self.demo
        if is_demo:
            found = False
            for p in list(self._demo_processes):
                if p["pid"] == pid:
                    self._demo_processes.remove(p)
                    found = True
                    break
            self.update_event.set()
            return found

        try:
            p = psutil.Process(pid)
            p.terminate()
            
            def _async_wait_worker():
                try:
                    p.wait(timeout=0.1)
                except psutil.TimeoutExpired:
                    try:
                        p.kill() # Escalated force kill if SIGTERM fails
                    except Exception:
                        pass
                except Exception:
                    pass
                    
            # Fire off wait monitor into background thread pools immediately
            threading.Thread(target=_async_wait_worker, daemon=True).start()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            return False
