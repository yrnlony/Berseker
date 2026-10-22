"""
config.py - all the settings you're likely to change live here.
Nothing in the other files should hardcode a resource-id, timeout, or path.
"""

from pathlib import Path

# ------------------------------------------------------------------
# ADB
# ------------------------------------------------------------------
ADB_PATH = "adb"          # or r"C:\platform-tools\adb.exe" if adb isn't on PATH
DEVICE_SERIAL = None       # None = auto-pick the only connected device.
                            # If you ever have 2 devices, set it to the serial
                            # from `adb devices`.

RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_SECONDS = 5

# ------------------------------------------------------------------
# App under test
# ------------------------------------------------------------------
PACKAGE = "com.md.workercenter"   # replace with your mock app's package name

# Selectors taken directly from the screen.xml you supplied.
# If your mock app differs, send a fresh dump and these get updated.
ID_ACCOUNT = f"{PACKAGE}:id/et_account"
ID_PASSWORD = f"{PACKAGE}:id/et_password"
ID_LOGIN_BTN = f"{PACKAGE}:id/click_login"

ID_NAV_MINE = f"{PACKAGE}:id/nav_mine"
ID_SIGN_OUT = f"{PACKAGE}:id/click_sign_out"
ID_LOGOUT_SURE = f"{PACKAGE}:id/click_sure"

LOGOUT_WAIT_SECONDS = 5  # time to wait for the logout to complete

# ------------------------------------------------------------------
# Account handling
# ------------------------------------------------------------------
REUSE_ACCOUNT_IF_CORRECT = True
# True  = if the account field already contains the expected account,
#         reuse it and skip re-entering it.
# False = always clear and re-enter the account for every fixture.

# Fill these in once you've dumped the result screens. Used by
# result_detector.py. Each is matched against `text` or `content-desc`
# anywhere in the dump. Leave the list empty to fall back to heuristics.
TEXT_USER_NOT_EXIST = ["User does not exist"]
TEXT_WRONG_PASSWORD = ["Username Or Password Error"]

# A resource-id (or text) that only appears once you're actually logged in.
# Confirmed from a real screen.xml of the post-login screen ("My Collection"
# with a Home/Score/Me bottom nav). Using the bottom_navigation resource-id
# rather than the "My Collection" text, since an id survives localization
# and doesn't depend on which tab/screen you land on after it.
SUCCESS_INDICATOR_ID = "com.md.workercenter:id/bottom_navigation"
SUCCESS_INDICATOR_TEXT = "My Collection"

# ------------------------------------------------------------------
# Timing
# ------------------------------------------------------------------
LAUNCH_WAIT_SECONDS = 8        # time to wait for the login screen after launch
RESULT_WAIT_SECONDS = 5       # time to wait for a result after submitting
UI_SETTLE_SECONDS = 0.6        # short pause after taps/typing before dumping
DUMP_RETRIES = 3
PER_ACCOUNT_RETRIES = 0        # retries for a single fixture on UI hiccups

# ------------------------------------------------------------------
# Files
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
FIXTURES_FILE = BASE_DIR / "fixtures.csv"
RESULTS_DIR = BASE_DIR / "results"

STATS_JSON = RESULTS_DIR / "stats.json"
RESULTS_CSV = RESULTS_DIR / "results.csv"
RESULTS_JSON = RESULTS_DIR / "results.json"
PROGRESS_FILE = RESULTS_DIR / "progress.json"   # for resume support
LOCAL_XML = BASE_DIR / "screen.xml"
REMOTE_XML = "/sdcard/screen.xml"
LOG_FILE = BASE_DIR / "automation.log"

# ------------------------------------------------------------------
# Modes
# ------------------------------------------------------------------
DRY_RUN = False   # overridden by --dry-run on the command line

RUN_MODE = "skip"
# "skip"  = skip fixtures already completed in progress.json
# "rerun" = run completed fixtures again
