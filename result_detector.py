"""
result_detector.py - turns a post-submit UI dump into one of:
    "success", "user_not_exist", "wrong_password", "unknown"

Keeping this separate from runner.py means you can tighten the detection
logic (e.g. once you know the real post-login screen) without touching
the test loop itself.
"""

import logging

import config
import ui

log = logging.getLogger("autotest")


def classify(root):
    if root is None:
        return "unknown", "no UI dump available"

    hit = ui.find_text_anywhere(root, config.TEXT_USER_NOT_EXIST)
    if hit:
        return "user_not_exist", hit

    hit = ui.find_text_anywhere(root, config.TEXT_WRONG_PASSWORD)
    if hit:
        return "wrong_password", hit

    # Prefer an explicit success indicator if you've configured one.
    if config.SUCCESS_INDICATOR_ID:
        if ui.find_node(root, resource_id=config.SUCCESS_INDICATOR_ID) is not None:
            return "success", "success indicator id matched"
    if config.SUCCESS_INDICATOR_TEXT:
        if ui.find_node(root, text=config.SUCCESS_INDICATOR_TEXT) is not None:
            return "success", "success indicator text matched"

    # Fallback heuristic: no error message, and the login screen is gone,
    # and we're still inside the app under test -> treat as success.
    if not ui.on_login_screen(root) and ui.foreground_package(root) == config.PACKAGE:
        return "success", "login screen gone, no error message, app in foreground"

    return "unknown", "no known indicator matched"
