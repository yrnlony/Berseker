"""
adb_client.py - everything that talks to `adb` directly.
No UI logic lives here, just device connection and shell commands.
"""

import logging
import subprocess
import sys
import time

import config

log = logging.getLogger("autotest")


class AdbError(Exception):
    pass


class AdbClient:
    def __init__(self):
        self.serial = None

    def run(self, *args, timeout=20, use_serial=True):
        """Run an adb command, return stdout text, raise AdbError on failure."""
        cmd = [config.ADB_PATH]
        if use_serial and self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            log.error("adb executable not found. Install platform-tools and add "
                      "it to PATH, or set ADB_PATH in config.py.")
            sys.exit(1)
        except subprocess.TimeoutExpired:
            raise AdbError(f"Timed out: {' '.join(cmd)}")

        out = p.stdout.decode("utf-8", errors="replace")
        err = p.stderr.decode("utf-8", errors="replace")
        problems = ("device offline", "no devices", "device not found",
                    "device unauthorized", "closed")
        if p.returncode != 0 or any(s in err.lower() for s in problems):
            raise AdbError(f"adb failed ({' '.join(args)}): {err.strip() or out.strip()}")
        return out

    def ensure_device(self):
        """Find a connected device, retrying if adb dropped. Sets self.serial."""
        for attempt in range(1, config.RECONNECT_ATTEMPTS + 1):
            try:
                out = self.run("devices", use_serial=False)
            except AdbError as e:
                log.warning(f"adb devices failed: {e}")
                out = ""

            ready, unauthorized = [], []
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    if parts[1] == "device":
                        ready.append(parts[0])
                    elif parts[1] == "unauthorized":
                        unauthorized.append(parts[0])

            if config.DEVICE_SERIAL:
                ready = [s for s in ready if s == config.DEVICE_SERIAL]

            if ready:
                self.serial = ready[0]
                if len(ready) > 1:
                    log.warning(f"Multiple devices found, using {self.serial}. "
                                f"Set DEVICE_SERIAL in config.py to choose.")
                log.info(f"Device connected: {self.serial}")
                return

            if unauthorized:
                log.warning("Device is 'unauthorized' - unlock the phone and accept "
                            "the 'Allow USB debugging' prompt.")
            else:
                log.warning("No device found.")
            log.info(f"Reconnect attempt {attempt}/{config.RECONNECT_ATTEMPTS}...")
            for cmd in (("start-server",), ("reconnect",)):
                try:
                    self.run(*cmd, use_serial=False)
                except AdbError:
                    pass
            time.sleep(config.RECONNECT_DELAY_SECONDS)

        raise AdbError("Could not connect to a device after several attempts.")

    # ---------------- convenience wrappers ----------------
    def launch_app(self):
        self.run("shell", "monkey", "-p", config.PACKAGE,
                  "-c", "android.intent.category.LAUNCHER", "1")

    def force_stop_app(self):
        self.run("shell", "am", "force-stop", config.PACKAGE)

    def tap(self, x, y):
        self.run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1, y1, x2, y2, duration_ms=400):
        self.run(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def keyevent(self, name):
        self.run("shell", "input", "keyevent", name)

    def type_text(self, text):
        escaped = text.replace("%", "%25").replace(" ", "%s")
        self.run("shell", "input", "text", escaped)

    def clear_field(self):
        self.run("shell", "input", "keyevent", *(["KEYCODE_DEL"] * 10))

    def screen_awake(self):
        return "mWakefulness=Awake" in self.run("shell", "dumpsys", "power")

    def wake_screen(self):
        self.keyevent("KEYCODE_WAKEUP")

    def keyguard_showing(self):
        out = self.run("shell", "dumpsys", "window")
        return ("isKeyguardShowing=true" in out) or ("mShowingLockscreen=true" in out)

    def keyboard_visible(self):
        try:
            return "mInputShown=true" in self.run("shell", "dumpsys", "input_method")
        except AdbError:
            return False

    def is_app_in_foreground(self):
        out = self.run("shell", "dumpsys", "window", "windows")
        return config.PACKAGE in out

    def pull(self, remote, local):
        self.run("pull", remote, str(local))

    def uiautomator_dump(self):
        return self.run("shell", "uiautomator", "dump", config.REMOTE_XML)
