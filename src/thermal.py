"""CPU thermal guard for long emulator runs."""
import glob, os, threading, time

CPU_SENSORS = ("k10temp", "zenpower", "coretemp")    # AMD, AMD (alternative driver), Intel


class ThermalGuard(threading.Thread):
    """Samples the hottest CPU package sensor once a second. Sets self.tripped once it has
    stayed above max_temp for more than hot_seconds. Does nothing if no sensor is found,
    as in many containers and VMs."""

    def __init__(self, max_temp: float = 99.0, hot_seconds: float = 30.0):
        super().__init__(daemon=True)
        self.paths = [os.path.join(os.path.dirname(p), "temp1_input")
                      for p in glob.glob("/sys/class/hwmon/hwmon*/name")
                      if open(p).read().strip() in CPU_SENSORS]
        self.max_temp, self.hot_seconds = max_temp, hot_seconds
        self.temp, self.peak, self.tripped = None, 0.0, threading.Event()

    def run(self):
        hot_since = None
        while self.paths and not self.tripped.is_set():
            t = max(int(open(p).read()) for p in self.paths) / 1000
            self.temp, self.peak = t, max(self.peak, t)
            hot_since = (hot_since or time.time()) if t > self.max_temp else None
            if hot_since and time.time() - hot_since > self.hot_seconds:
                self.tripped.set()
            time.sleep(1)
