"""
ui.py - reading the UI hierarchy and interacting with elements by selector,
never by blind fixed coordinates.
"""

import logging
import re
import shutil
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import config
from adb_client import AdbError

log = logging.getLogger("autotest")


def dump_ui(adb):
    """Dump the UI hierarchy, pull it locally, return the parsed XML root (or None)."""
    last = ""
    for attempt in range(1, config.DUMP_RETRIES + 1):
        try:
            out = adb.uiautomator_dump()
        except AdbError as e:
            last = str(e)
            time.sleep(1)
            continue
        if "dumped to" in out.lower():
            adb.pull(config.REMOTE_XML, config.LOCAL_XML)
            try:
                return ET.parse(config.LOCAL_XML).getroot()
            except ET.ParseError as e:
                last = f"XML parse error: {e}"
        else:
            last = out.strip()
        time.sleep(1)  # screen may be mid-transition
    log.warning(f"UI dump failed after {config.DUMP_RETRIES} tries: {last}")
    return None


def find_node(root, resource_id=None, text=None, desc=None):
    if root is None:
        return None
    for n in root.iter("node"):
        if resource_id and n.get("resource-id") == resource_id:
            return n
        if text and n.get("text") == text:
            return n
        if desc and n.get("content-desc") == desc:
            return n
    return None


def find_text_anywhere(root, needles):
    """Return the first needle (from a list) found in any node's text or
    content-desc, or None."""
    if root is None:
        return None
    for n in root.iter("node"):
        t = (n.get("text") or "")
        d = (n.get("content-desc") or "")
        for needle in needles:
            if needle and (needle in t or needle in d):
                return needle
    return None


def center(node):
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
    return (x1 + x2) // 2, (y1 + y2) // 2


def tap_node(adb, node, label=""):
    x, y = center(node)
    log.info(f"Tapping {label or 'element'} at ({x}, {y})")
    adb.tap(x, y)
    time.sleep(config.UI_SETTLE_SECONDS)


def foreground_package(root):
    first = next(root.iter("node"), None) if root is not None else None
    return first.get("package") if first is not None else None


def on_login_screen(root):
    return (find_node(root, resource_id=config.ID_ACCOUNT) is not None and
            find_node(root, resource_id=config.ID_LOGIN_BTN) is not None)


def wait_for_login_screen(adb, timeout):
    end = time.time() + timeout
    root = None
    while time.time() < end:
        root = dump_ui(adb)
        if on_login_screen(root):
            return root
        time.sleep(1)
    return None


def save_debug_dump(root, reason, account_label=""):
    """Save the current XML + a readable element list for later debugging."""
    log.error(f"DEBUG: {reason}")
    config.RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"fail_{account_label}_{stamp}.xml" if account_label else f"fail_{stamp}.xml"
    dest = config.RESULTS_DIR / name
    if config.LOCAL_XML.exists():
        shutil.copy(config.LOCAL_XML, dest)
        log.error(f"DEBUG: saved UI dump to {dest}")
    if root is not None:
        log.error(f"DEBUG: foreground package = {foreground_package(root)}")
        log.error("DEBUG: elements (resource-id | text | desc | clickable | bounds):")
        for n in root.iter("node"):
            if n.get("resource-id") or n.get("text") or n.get("content-desc"):
                log.error(f"  {n.get('resource-id')} | {n.get('text')} | "
                          f"{n.get('content-desc')} | {n.get('clickable')} | "
                          f"{n.get('bounds')}")
    return dest
