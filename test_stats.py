"""Persistent test statistics for the automation runner.

This module records aggregate statistics without storing passwords, fixture_id
values that contain passwords, or arbitrary ADB command text.
"""

import csv
import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("autotest")

SAFE_DETAIL_PATTERNS = (
    ("login_screen_unavailable", re.compile(r"could not reach login screen", re.I)),
    ("required_ui_element_missing", re.compile(r"field/button not found|password field missing|login button vanished", re.I)),
    ("wrong_password", re.compile(r"wrong_password", re.I)),
    ("user_not_exist", re.compile(r"user_not_exist", re.I)),
    ("result_timeout", re.compile(r"no successful login detected|no definitive result", re.I)),
    ("app_crash_or_closed", re.compile(r"crash|closed|left the foreground", re.I)),
    ("adb_error", re.compile(r"\badb\b|device|unauthorized|offline|not found", re.I)),
)


def _json_safe(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _safe_fixture_label(index):
    """Return a stable, non-secret fixture identifier based on CSV row order."""
    return f"fixture-{index + 1:04d}"


def classify_failure_reason(result, detail):
    result = (result or "").strip().lower()
    detail = (detail or "").strip()

    if result == "success":
        return "success"
    if result == "user_not_exist":
        return "user_not_exist"
    if result == "wrong_password":
        return "wrong_password"
    if result == "crash_or_closed":
        return "app_crash_or_closed"
    if result == "dry_run":
        return "dry_run"
    if result == "error":
        return "error"

    for name, pattern in SAFE_DETAIL_PATTERNS:
        if pattern.search(detail):
            return name

    return "unknown_failure"


class StatsCollector:
    """Collect current-run and historical aggregate statistics.

    stats.json is an aggregate/cache file, not a second per-attempt result
    ledger. The existing results.csv remains the detailed result record.
    """

    SCHEMA_VERSION = 1

    def __init__(self, stats_path, total, mode="normal", selected_count=None):
        self.path = Path(stats_path)
        self.total = int(total)
        self.mode = mode
        self.selected_count = int(selected_count if selected_count is not None else total)
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.started_perf = time.perf_counter()
        self.completed = 0
        self.attempted = 0
        self.successes = 0
        self.failures = 0
        self.errors = 0
        self.dry_runs = 0
        self.skipped = 0
        self.retries = 0
        self.durations = []
        self.fastest = None
        self.slowest = None
        self.tests = []
        self.failure_reasons = Counter()
        self.fixture_stats = defaultdict(lambda: {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "errors": 0,
            "dry_runs": 0,
            "retries": 0,
            "total_runtime_seconds": 0.0,
            "last_result": None,
            "last_detail": None,
        })
        self.historical = self._load()
        self.historical.setdefault("schema_version", self.SCHEMA_VERSION)
        self.historical.setdefault("runs", [])
        self.historical.setdefault("fixture_totals", {})
        self.historical.setdefault("failure_reasons", {})
        self.historical.setdefault("lifetime", self._empty_lifetime())
        self.historical.setdefault("lifetime_committed", dict(self.historical["lifetime"]))

    @staticmethod
    def _empty_lifetime():
        return {
            "attempted": 0,
            "successes": 0,
            "failures": 0,
            "errors": 0,
            "dry_runs": 0,
            "retries": 0,
            "skipped": 0,
            "runtime_seconds": 0.0,
        }

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            log.warning("Could not read existing stats.json; starting a new statistics history.")
            return {}

    def set_skipped(self, count):
        self.skipped = max(0, int(count))

    def set_retry_count(self, count):
        self.retries = max(0, int(count))

    def start_test(self, position, fixture_label):
        log.info("Test %s/%s - %s", position, self.total, fixture_label)
        return time.perf_counter()

    def record(self, record, duration_seconds, fixture_index, retry_count=0):
        result = (record.get("result") or "error").strip().lower()
        duration = round(max(0.0, float(duration_seconds)), 3)
        fixture_label = _safe_fixture_label(fixture_index)
        test_timestamp = datetime.now().isoformat(timespec="seconds")
        test_number = self.completed + 1

        self.completed += 1
        self.attempted += 1
        self.retries += max(0, int(retry_count))
        self.durations.append(duration)

        if self.fastest is None or duration < self.fastest["seconds"]:
            self.fastest = {"fixture": fixture_label, "seconds": duration}
        if self.slowest is None or duration > self.slowest["seconds"]:
            self.slowest = {"fixture": fixture_label, "seconds": duration}

        bucket = self.fixture_stats[fixture_label]
        bucket["attempts"] += 1
        bucket["retries"] += max(0, int(retry_count))
        bucket["total_runtime_seconds"] = round(bucket["total_runtime_seconds"] + duration, 3)
        bucket["last_result"] = result

        detail = record.get("detail", "")
        reason = classify_failure_reason(result, detail)
        bucket["last_detail"] = self._sanitize_detail(detail, reason)

        if result == "success":
            self.successes += 1
            bucket["successes"] += 1
        elif result == "dry_run":
            self.dry_runs += 1
            bucket["dry_runs"] += 1
        elif result == "error":
            self.errors += 1
            self.failures += 1
            bucket["failures"] += 1
            bucket["errors"] += 1
            self.failure_reasons[reason] += 1
        else:
            self.failures += 1
            bucket["failures"] += 1
            self.failure_reasons[reason] += 1
        self.tests.append({
            "test_number": test_number,
            "timestamp": test_timestamp,
            "fixture": fixture_label,
            "result": result,
            "duration_seconds": duration,
            "retry_count": max(0, int(retry_count)),
            "failure_reason": reason,
})
      
        self._persist_current_state()

    @staticmethod
    def _sanitize_detail(detail, reason):
        detail = str(detail or "").strip()
        if not detail:
            return reason
        # Never persist values that look like passwords or credential payloads.
        detail = re.sub(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+", r"\1=[REDACTED]", detail)
        detail = re.sub(r"(?i)(token|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", detail)
        detail = detail.replace("|", "/")
        return detail[:240]

    def _current_summary(self):
        actual = self.successes + self.failures
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": self.mode,
            "total_selected": self.total,
            "attempted": self.attempted,
            "successful": self.successes,
            "failed": self.failures,
            "errors": self.errors,
            "dry_runs": self.dry_runs,
            "skipped": self.skipped,
            "retries": self.retries,
            "success_rate_percent": round((self.successes / actual) * 100, 2) if actual else 0.0,
            "failure_rate_percent": round((self.failures / actual) * 100, 2) if actual else 0.0,
            "runtime_seconds": round(time.perf_counter() - self.started_perf, 3),
            "average_test_seconds": round(sum(self.durations) / len(self.durations), 3) if self.durations else 0.0,
            "fastest": self.fastest,
            "slowest": self.slowest,
            "tests": list(self.tests),
            "failure_reasons": dict(self.failure_reasons),
            "fixtures": {k: dict(v) for k, v in self.fixture_stats.items()},
        }

    def _persist_current_state(self):
        data = dict(self.historical)
        data["schema_version"] = self.SCHEMA_VERSION
        data["current_run"] = self._current_summary()
        data["lifetime"] = self._calculate_lifetime()
        data["lifetime_committed"] = dict(self.historical.get("lifetime_committed", self.historical.get("lifetime", self._empty_lifetime())))
        data["fixture_totals"] = self._merge_fixture_totals()
        data["failure_reasons"] = self._merge_counter(data.get("failure_reasons", {}), self.failure_reasons)
        self._atomic_write(data)

    def _calculate_lifetime(self):
        lifetime = dict(self.historical.get("lifetime_committed", self.historical.get("lifetime", self._empty_lifetime())))
        lifetime["attempted"] = int(lifetime.get("attempted", 0)) + self.attempted
        lifetime["successes"] = int(lifetime.get("successes", 0)) + self.successes
        lifetime["failures"] = int(lifetime.get("failures", 0)) + self.failures
        lifetime["errors"] = int(lifetime.get("errors", 0)) + self.errors
        lifetime["dry_runs"] = int(lifetime.get("dry_runs", 0)) + self.dry_runs
        lifetime["retries"] = int(lifetime.get("retries", 0)) + self.retries
        lifetime["skipped"] = int(lifetime.get("skipped", 0)) + self.skipped
        lifetime["runtime_seconds"] = round(float(lifetime.get("runtime_seconds", 0.0)) + sum(self.durations), 3)
        return lifetime

    def _merge_fixture_totals(self):
        merged = dict(self.historical.get("fixture_totals", {}))
        for key, current in self.fixture_stats.items():
            old = dict(merged.get(key, {}))
            for field in ("attempts", "successes", "failures", "errors", "dry_runs", "retries"):
                old[field] = int(old.get(field, 0)) + int(current.get(field, 0))
            old["total_runtime_seconds"] = round(float(old.get("total_runtime_seconds", 0.0)) + float(current.get("total_runtime_seconds", 0.0)), 3)
            old["last_result"] = current.get("last_result")
            old["last_detail"] = current.get("last_detail")
            merged[key] = old
        return merged

    @staticmethod
    def _merge_counter(old, current):
        merged = Counter(old or {})
        merged.update(current)
        return dict(merged)

    def _atomic_write(self, data):
        self.path.parent.mkdir(exist_ok=True, parents=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
        temp.replace(self.path)

    def finish(self, interrupted=False):
        summary = self._current_summary()
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary["interrupted"] = bool(interrupted)

        data = dict(self.historical)
        runs = list(data.get("runs", []))
        runs.append(summary)
        data["runs"] = runs[-100:]
        data["current_run"] = summary
        data["lifetime"] = self._calculate_lifetime()
        data["lifetime_committed"] = self._calculate_lifetime()
        data["fixture_totals"] = self._merge_fixture_totals()
        data["failure_reasons"] = self._merge_counter(data.get("failure_reasons", {}), self.failure_reasons)
        data["schema_version"] = self.SCHEMA_VERSION
        self._atomic_write(data)
        return summary

    def log_summary(self):
        summary = self._current_summary()
        actual = summary["successful"] + summary["failed"]
        log.info("----- TEST STATISTICS -----")
        log.info("Total selected: %s", summary["total_selected"])
        log.info("Attempted: %s", summary["attempted"])
        log.info("Successful: %s", summary["successful"])
        log.info("Failed: %s", summary["failed"])
        log.info("Errors: %s", summary["errors"])
        log.info("Skipped: %s", summary["skipped"])
        log.info("Dry runs: %s", summary["dry_runs"])
        log.info("Retries: %s", summary["retries"])
        log.info("Success rate: %.2f%%", summary["success_rate_percent"])
        log.info("Failure rate: %.2f%%", summary["failure_rate_percent"])
        log.info("Total runtime: %.2fs", summary["runtime_seconds"])
        log.info("Average test time: %.2fs", summary["average_test_seconds"])
        if self.fastest:
            log.info("Fastest: %s (%.2fs)", self.fastest["fixture"], self.fastest["seconds"])
        if self.slowest:
            log.info("Slowest: %s (%.2fs)", self.slowest["fixture"], self.slowest["seconds"])
        if self.failure_reasons:
            log.info("Failure reasons:")
            for reason, count in self.failure_reasons.most_common():
                log.info("  %s: %s", reason, count)
        log.info("Statistics saved to %s", self.path)
