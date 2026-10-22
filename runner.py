"""
runner.py - the main test loop.

Usage (from the project folder):
    py runner.py                 # normal run, resumes if a progress file exists
    py runner.py --dry-run       # find fields/button, don't submit
    py runner.py --restart       # ignore saved progress, start from fixture 1
    py runner.py --only CU-05    # run a single fixture (handy for debugging)
"""

import argparse
import csv
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from test_stats import StatsCollector

def _load_module(module_name):
    try:
        return __import__(module_name)
    except ImportError:
        module_path = Path(__file__).resolve().with_name(f"{module_name}.py")
        if not module_path.exists():
            raise

        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


config = _load_module("config")
result_detector = _load_module("result_detector")
ui = _load_module("ui")

try:
    adb_module = __import__("adb_client")
    AdbClient = adb_module.AdbClient
    AdbError = adb_module.AdbError
except ImportError:
    module_path = Path(__file__).resolve().with_name("adb_client.py")

    if not module_path.exists():
        raise

    spec = importlib.util.spec_from_file_location("adb_client", module_path)
    if spec is None or spec.loader is None:
        raise

    module = importlib.util.module_from_spec(spec)
    sys.modules["adb_client"] = module
    spec.loader.exec_module(module)
    AdbClient = module.AdbClient
    AdbError = module.AdbError


log = logging.getLogger("autotest")


def setup_logging():
    config.RESULTS_DIR.mkdir(exist_ok=True, parents=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        ],
    )


def load_fixtures():
    if not config.FIXTURES_FILE.exists():
        log.error(f"Fixtures file not found: {config.FIXTURES_FILE}")
        sys.exit(1)

    fixtures = []

    with open(config.FIXTURES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            account = row.get("account", "").strip()
            test_password = row.get("test_password", "").strip()
            expected_result = row.get("expected_result", "").strip().lower()

            if not account or not test_password or not expected_result:
                continue

            fixtures.append(
                (account, test_password, expected_result)
            )

    if not fixtures:
        log.error("No fixtures loaded - check fixtures.csv")
        sys.exit(1)

    # Fixture identity is (account, test_password) - the same account can
    # legitimately appear multiple times with different passwords (e.g.
    # several known-invalid values that should each be denied), so rows
    # are NOT deduplicated by account alone.
    return fixtures


def fixture_id(account, test_password):
    return f"{account}|{test_password}"


def load_progress():
    if config.PROGRESS_FILE.exists():
        try:
            return json.loads(
                config.PROGRESS_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return {}

    return {}


def save_progress(last_completed_fixture_id):
    config.RESULTS_DIR.mkdir(exist_ok=True, parents=True)

    config.PROGRESS_FILE.write_text(
        json.dumps(
            {
                "last_completed_fixture_id": last_completed_fixture_id,
                "updated_at": datetime.now().isoformat(),
            }
        ),
        encoding="utf-8",
    )

def load_recorded_fixture_ids():
    """Return fixture IDs that already have a recorded result."""
    recorded = set()

    if not config.RESULTS_CSV.exists():
        return recorded

    try:
        with open(
            config.RESULTS_CSV,
            newline="",
            encoding="utf-8",
        ) as f:
            reader = csv.DictReader(f)

            for row in reader:
                fid = row.get("fixture_id", "").strip()

                if fid and row.get("result", "").strip().lower() == "success":
                    recorded.add(fid)

    except (OSError, csv.Error):
        log.warning(
            "Could not read existing results.csv; "
            "restart will not skip recorded fixtures."
        )

    return recorded


def load_successful_batches():
    """Return batch IDs that already have a successful fixture."""
    successful_batches = set()

    if not config.RESULTS_CSV.exists():
        return successful_batches

    try:
        with open(
            config.RESULTS_CSV,
            newline="",
            encoding="utf-8",
        ) as f:
            reader = csv.DictReader(f)

            for row in reader:
                account = row.get("account", "").strip()
                result = row.get("result", "").strip().lower()

                if account and result == "success":
                    successful_batches.add(account)

    except (OSError, csv.Error):
        log.warning(
            "Could not read existing results.csv; "
            "previously successful batches will not be skipped."
        )

    return successful_batches


def append_result(row, csv_rows):
    csv_rows.append(row)

    config.RESULTS_DIR.mkdir(exist_ok=True, parents=True)

    write_header = not config.RESULTS_CSV.exists()

    with open(
        config.RESULTS_CSV,
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=row.keys(),
        )

        if write_header:
            writer.writeheader()

        writer.writerow(row)

    config.RESULTS_JSON.write_text(
        json.dumps(csv_rows, indent=2),
        encoding="utf-8",
    )


def ensure_app_ready(adb):
    """
    Make sure the device is awake, unlocked, and the app is on the login
    screen. Returns the login-screen XML root, or None if it couldn't get
    there.
    """

    if not adb.screen_awake():
        log.info("Screen is off, waking it")
        adb.wake_screen()
        time.sleep(1.5)

    if adb.keyguard_showing():
        log.error(
            "Phone's own lock screen is showing. Unlock the phone manually "
            "and re-run. This tool only automates the app under test."
        )
        return None

    root = ui.dump_ui(adb)

    if (
        root is None
        or ui.foreground_package(root) != config.PACKAGE
        or not ui.on_login_screen(root)
    ):
        log.info(f"Launching {config.PACKAGE}")

        adb.launch_app()

        root = ui.wait_for_login_screen(
            adb,
            config.LAUNCH_WAIT_SECONDS,
        )

    return root


def run_one_fixture(
    adb,
    account,
    test_password,
    expected_result,
    dry_run,
):
    """Returns a dict describing the outcome of this one fixture.

    Exactly ONE login attempt per fixture - no retries. Each call enters
    the account fresh (every account+test_password combo is its own
    fixture, even when the account repeats across fixtures). If the
    result can't be classified, it's recorded as "unknown" and the
    caller moves on to the next fixture - this function does not retry.
    """

    fid = fixture_id(account, test_password)
    log.info(f"Starting fixture {fid}")

    record = {
        "fixture_id": fid,
        "account": account,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "result": "error",
        "expected_result": expected_result,
        "detail": "",
    }

    # ================================================================
    # Reach the login screen.
    # ================================================================

    root = ensure_app_ready(adb)

    if root is None:
        record["detail"] = "could not reach login screen"

        ui.save_debug_dump(
            None,
            f"{fid}: login screen never appeared",
            account,
        )

        return record

    log.info("Login screen detected")

    acc_field = ui.find_node(
        root,
        resource_id=config.ID_ACCOUNT,
    )

    pwd_field = ui.find_node(
        root,
        resource_id=config.ID_PASSWORD,
    )

    btn = ui.find_node(
        root,
        resource_id=config.ID_LOGIN_BTN,
    )

    if (
        acc_field is None
        or pwd_field is None
        or btn is None
    ):
        ui.save_debug_dump(
            root,
            f"{fid}: a required field/button is missing",
            account,
        )

        record["detail"] = "field/button not found"

        return record

    # ================================================================
    # ACCOUNT - only enter the account if the current field does not
    # already contain the expected account.
    # ================================================================

    current_account = (acc_field.get("text") or "").strip()
    log.info(f"Current account field text detected: {current_account!r}")

    if config.REUSE_ACCOUNT_IF_CORRECT and current_account == account:
        log.info(
            f"Account already correct ({account}); "
            "skipping account entry"
        )
    else:
        ui.tap_node(
            adb,
            acc_field,
            "account field",
        )

        time.sleep(0.5)

        adb.clear_field()
        adb.type_text(account)

        log.info("Username entered")

        if adb.keyboard_visible():
            log.info("Dismissing account keyboard")
            adb.keyevent("KEYCODE_BACK")
            time.sleep(0.6)

    # ================================================================
    # PASSWORD
    # ================================================================

    root = ui.dump_ui(adb)

    pwd_field = ui.find_node(
        root,
        resource_id=config.ID_PASSWORD,
    )

    if pwd_field is None:
        ui.save_debug_dump(
            root,
            f"{fid}: password field missing",
            account,
        )

        record["detail"] = "password field missing"

        return record

    ui.tap_node(
        adb,
        pwd_field,
        "password field",
    )

    time.sleep(0.5)

    adb.clear_field()
    adb.type_text(test_password)

    log.info("Password entered")

    if adb.keyboard_visible():
        log.info("Dismissing password keyboard")
        adb.keyevent("KEYCODE_BACK")
        time.sleep(0.6)

    log.info("Credentials entered and keyboard dismissed")

    # ================================================================
    # LOGIN BUTTON
    # ================================================================

    root = ui.dump_ui(adb)

    btn = ui.find_node(
        root,
        resource_id=config.ID_LOGIN_BTN,
    )

    if btn is None:
        ui.save_debug_dump(
            root,
            f"{fid}: login button vanished before submit",
            account,
        )

        record["detail"] = "login button vanished"

        return record

    if dry_run:
        x, y = ui.center(btn)

        log.info(
            f"DRY RUN: would tap Login at "
            f"({x}, {y}) - not submitting"
        )

        record["result"] = "dry_run"
        record["detail"] = "fields located, submit skipped"

        return record

    ui.tap_node(
        adb,
        btn,
        "Login button",
    )

    log.info("Login submitted")

    # ================================================================
    # RESULT DETECTION - one submission, polled for up to 5 seconds
    # for the app to respond. This is NOT a retry: nothing is
    # resubmitted here, this just waits for a response to the single
    # login tap above.
    # ================================================================

    end = time.time() + 5

    outcome = "unknown"
    detail = "no definitive result within 5 seconds"

    while time.time() < end:

        if not adb.is_app_in_foreground():
            outcome = "crash_or_closed"
            detail = "app left the foreground"
            break

        root = ui.dump_ui(adb)

        outcome, detail = result_detector.classify(root)

        if outcome != "unknown":
            break

        time.sleep(0.25)

    record["result"] = outcome
    record["detail"] = detail

    if outcome == "crash_or_closed":
        log.error(f"{fid}: app crashed or closed")
        adb.force_stop_app()
        time.sleep(1)
        return record

    if outcome == "unknown":
        outcome = "failed"
        detail = "no successful login detected within 5 seconds"
        record["result"] = outcome
        record["detail"] = detail

    log.info(
        f"Result for {fid}: "
        f"{outcome} ({detail})"
    )
    
    if outcome == "failed":
        log.info(f"{fid}: failure deadline reached; skipping cleanup and moving on")
        return record


    # ================================================================
    # LOGOUT - return to the login screen before the next fixture
    # ================================================================

    root = ui.dump_ui(adb)

    nav_mine = ui.find_node(
        root,
        resource_id=config.ID_NAV_MINE,
    )

    if nav_mine is None:
        log.error(f"{fid}: Me navigation button not found; cannot logout")
        return record

    ui.tap_node(
        adb,
        nav_mine,
        "Me navigation",
    )

    # Scroll down once on the Me page so SIGN OUT becomes visible.
    adb.swipe(360, 1200, 360, 500, 400)
    time.sleep(0.6)

    root = ui.dump_ui(adb)

    sign_out = ui.find_node(
        root,
        resource_id=config.ID_SIGN_OUT,
    )

    if sign_out is None:
        log.error(f"{fid}: SIGN OUT button not found; cannot logout")
        return record

    ui.tap_node(
        adb,
        sign_out,
        "SIGN OUT",
    )

    root = ui.dump_ui(adb)

    logout_sure = ui.find_node(
        root,
        resource_id=config.ID_LOGOUT_SURE,
    )

    if logout_sure is None:
        log.error(f"{fid}: logout confirmation button not found; cannot logout")
        return record

    ui.tap_node(
        adb,
        logout_sure,
        "Sure",
    )

    login_root = ui.wait_for_login_screen(
        adb,
        config.LOGOUT_WAIT_SECONDS,
    )

    if login_root is None:
        log.error(
            f"{fid}: login screen did not appear after logout; "
            "stopping before next fixture"
        )
        raise RuntimeError(
            f"{fid}: logout failed - login screen did not reappear"
        )

    log.info(f"{fid}: logout successful; login screen detected")

    return record



def main():
    stats = None

    try:
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="locate fields/button but never submit",
        )

        parser.add_argument(
            "--restart",
            action="store_true",
            help="ignore saved progress, start from the first fixture",
        )
        parser.add_argument(
            "--rerun",
            action="store_true",
            help="run fixtures even if they are already completed",
        )

        parser.add_argument(
            "--only",
            metavar="ACCOUNT",
            help="run a single fixture by account id, ignore resume state",
        )

        parser.add_argument(
            "--only-batches",
            nargs="+",
            metavar="BATCH",
            help="run only the specified batches",
        )

        args = parser.parse_args()

        dry_run = args.dry_run or config.DRY_RUN

        setup_logging()

        fixtures = load_fixtures()
        skipped_count = 0

        if args.only_batches:
            fixtures = [
                f for f in fixtures
                if f[0] in args.only_batches
            ]

            if not fixtures:
                log.error(
                    f"No fixtures found for batches: "
                    f"{', '.join(args.only_batches)}"
                )
                sys.exit(1)

        elif args.only:
            if "|" in args.only:
                # Exact fixture: account|test_password
                fixtures = [
                    f for f in fixtures
                    if fixture_id(f[0], f[1]) == args.only
                ]
            else:
                # Account only: run all fixtures for this account
                fixtures = [
                    f for f in fixtures
                    if f[0] == args.only
                ]

            if not fixtures:
                log.error(
                    f"No fixture found for account {args.only}"
                )
                sys.exit(1)

        elif not args.restart and not args.rerun:
            progress = load_progress()

            last = progress.get(
                "last_completed_fixture_id"
            )

            if last:
                idx = next(
                    (
                        i
                        for i, f in enumerate(fixtures)
                        if fixture_id(f[0], f[1]) == last
                    ),
                    None,
                )

                if idx is not None:
                    log.info(
                        f"Resuming after {last}"
                    )

                    fixtures = fixtures[idx + 1:]

            successful_batches = load_successful_batches()

            if successful_batches:
                remaining = []

                for fixture in fixtures:
                    batch_id = fixture[0]
                    fid = fixture_id(fixture[0], fixture[1])

                    if batch_id in successful_batches:
                        skipped_count += 1
                        log.info(
                            f"Skipping {fid}: "
                            f"batch {batch_id} already completed successfully"
                        )
                        continue

                    remaining.append(fixture)

                fixtures = remaining

        elif args.restart and not args.rerun:
            recorded = load_recorded_fixture_ids()
            successful_batches = load_successful_batches()

            if recorded or successful_batches:
                remaining = []

                for fixture in fixtures:
                    fid = fixture_id(fixture[0], fixture[1])
                    batch_id = fixture[0]

                    if fid in recorded:
                        skipped_count += 1
                        continue

                    if batch_id in successful_batches:
                        skipped_count += 1
                        log.info(
                            f"Skipping {fid}: "
                            f"batch {batch_id} already completed successfully"
                        )
                        continue

                    remaining.append(fixture)

                fixtures = remaining

        if not fixtures:

            if args.restart and skipped_count:
                log.info(
                    "Restart complete: all fixtures were already recorded."
                )
            else:
                log.info(
                    "Nothing left to run (already completed). "
                    "Use --restart to run again."
                )

            return

        # Keep this explicit in this scope so the loop below and the
        # dry-run logic share a single defined value.
        dry_run = bool(
            getattr(args, "dry_run", False)
            or getattr(config, "DRY_RUN", False)
        )

        stats = StatsCollector(
            config.STATS_JSON,
            total=len(fixtures),
            mode=(
                "dry_run" if dry_run
                else "restart" if args.restart
                else "rerun" if args.rerun
                else "normal"
            ),
            selected_count=len(fixtures),
        )

        stats.set_skipped(skipped_count)

        adb = AdbClient()

        adb.ensure_device()

        csv_rows = []

        # Skip accounts that already have at least one successful result
        # in the persisted CSV when not explicitly rerunning the suite.
        completed_batches = (
            set() if args.rerun else load_successful_batches()
        )

        totals = {
            "success": 0,
            "user_not_exist": 0,
            "wrong_password": 0,
            "failed": 0,
            "dry_run": 0,
            "unknown": 0,
            "crash_or_closed": 0,
            "error": 0,
        }

        for fixture_index, (account, test_password, expected_result) in enumerate(fixtures):

            batch_id = account
            fid = fixture_id(account, test_password)

            if batch_id in completed_batches:
                skipped_count += 1

                log.info(
                    f"Skipping {fid}: "
                    f"batch {batch_id} already succeeded"
                )

                continue

            test_start = stats.start_test(
                fixture_index + 1,
                f"fixture-{fixture_index + 1:04d}",
            )

            try:
                adb.ensure_device()

            except AdbError as e:

                log.error(
                    f"Lost the device and could not reconnect: {e}"
                )

                break

            try:

                record = run_one_fixture(
                    adb,
                    account,
                    test_password,
                    expected_result,
                    dry_run,
                )

            except AdbError as e:

                log.error(
                    f"ADB error on {account}: {e}"
                )

                record = {
                    "account": account,
                    "timestamp": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "result": "error",
                    "expected_result": expected_result,
                    "detail": str(e),
                }

            totals[record["result"]] = (
                totals.get(record["result"], 0) + 1
            )

            append_result(
                record,
                csv_rows,
            )

            test_duration = time.perf_counter() - test_start

            stats.record(
                record,
                test_duration,
                fixture_index,
                retry_count=0,
            )

            save_progress(fid)

            if record["result"].strip().lower() == "success":
                completed_batches.add(batch_id)

                log.info(
                    f"Batch {batch_id} completed successfully via {fid}. "
                    f"Remaining fixtures in this batch will be skipped."
                )

                log.info(
                    f"Moving to next batch after {batch_id}"
                )
            else:
                log.info(
                    f"Moving to next fixture after {fid}"
                )

        log.info("----- SUMMARY -----")

        log.info(
            f"Total fixtures run: {len(csv_rows)}"
        )
        stats.finish()
        stats.log_summary()

        for key, count in totals.items():

            if count:
                log.info(
                    f"  {key}: {count}"
                )

        log.info(
            f"Results saved to {config.RESULTS_CSV} "
            f"and {config.RESULTS_JSON}"
        )

    except KeyboardInterrupt:
        if stats is not None:
            stats.finish(interrupted=True)
            stats.log_summary()
        log.info("Stopped by user (progress saved, re-run to resume)")


if __name__ == "__main__":
    main()
