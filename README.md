# Mock App Login UI-Test Runner

A fixtures-driven ADB + UIAutomator test runner for your mock Android app.
Each account in `fixtures.csv` has its own predetermined password — the
runner never guesses or iterates credentials, it just replays known
account/password pairs and records what the app says.

## What each file does

| File | Purpose |
|---|---|
| `config.py` | All settings: ADB path, package name, selectors, timeouts, file paths. Edit this first. |
| `fixtures.csv` | Your test accounts and their real passwords. Replace the placeholders. |
| `adb_client.py` | Talks to `adb`: device detection/reconnection, taps, typing, launching the app. |
| `ui.py` | Dumps the UI hierarchy and finds elements by resource-id/text, never by blind coordinates. Saves debug dumps on failure. |
| `result_detector.py` | Reads a post-submit UI dump and classifies it as success / user_not_exist / wrong_password / unknown. |
| `runner.py` | The main loop: for each fixture, log in, read the result, save it, move to the next. Handles retries, crashes, resume. |
| `results/` | Created automatically: `results.csv`, `results.json`, `progress.json`, and a saved UI dump for every failure. |
| `automation.log` | Full run log (same content as the console, plus everything that scrolled past). |

## One-time setup

1. Install Python from python.org, ticking "Add python.exe to PATH".
2. Make sure Android platform-tools (`adb`) is installed and on PATH.
3. Open the project folder in VS Code: `File > Open Folder... > mock-login-tester`.
4. No pip packages are needed (see `requirements.txt`).

## Before your first run

1. **Fill in `fixtures.csv`** with your 24 real test accounts and their actual
   passwords, replacing `REPLACE_ME_01` etc.
2. **Confirm the selectors in `config.py`** match your mock app. The ones
   there now (`et_account`, `et_password`, `click_login`) came from the
   `screen.xml` you supplied for the login screen. If your mock app's
   package name or IDs differ, update `PACKAGE`, `ID_ACCOUNT`,
   `ID_PASSWORD`, `ID_LOGIN_BTN`.
3. **Dump a post-login (success) screen** on the real device, and a
   post-failed-login screen too, then send me both. I'll fill in
   `SUCCESS_INDICATOR_ID` / `SUCCESS_INDICATOR_TEXT` and double check
   `TEXT_USER_NOT_EXIST` / `TEXT_WRONG_PASSWORD` against the exact wording.
   Until then, the runner falls back to "login screen disappeared without
   an error message" as its definition of success, which works but is
   less precise.

## Commands (PowerShell, from the project folder)

```powershell
cd path\to\mock-login-tester

# 1. Confirm the device is visible
adb devices

# 2. Dry run: locates fields and the button, never taps Login.
#    Use this to confirm selectors work before testing for real.
py runner.py --dry-run

# 3. Run a single fixture, useful while debugging
py runner.py --only CU-01

# 4. Full run across all fixtures (resumes automatically if interrupted)
py runner.py

# 5. Ignore saved progress and start over from fixture 1
py runner.py --restart
```

## Resuming after an interruption

Every completed fixture updates `results/progress.json`. If you stop the
script (Ctrl+C, laptop sleeps, phone disconnects) and run `py runner.py`
again without `--restart`, it picks up right after the last completed
account.

## Debugging in VS Code

- Set breakpoints directly in `runner.py` (e.g. inside `run_one_fixture`)
  and use **Run > Start Debugging** (F5) with a "Python File" launch
  config pointed at `runner.py`. Add `"args": ["--only", "CU-01"]` to
  your `launch.json` to debug just one fixture at a time.
- Every failure automatically saves the full UI dump and a readable
  element list to `results/fail_<account>_<timestamp>.xml` and the log,
  so you usually don't need a debugger at all — check the log first.
- `automation.log` has everything; the console shows the same in real
  time.

## Output

- `results/results.csv` and `results/results.json` — one row per fixture:
  account, timestamp, result, detail.
- Console/log summary at the end, e.g.:

```
----- SUMMARY -----
Total fixtures run: 24
  success: 20
  wrong_password: 3
  user_not_exist: 1
Results saved to results/results.csv and results/results.json
```

## Extending

- Different account series (e.g. an `F`-variant series) just needs a
  different `fixtures.csv` — the runner doesn't care how the account
  strings are formatted, it just reads whatever CSV `config.FIXTURES_FILE`
  points to.
- To test a different app, update `PACKAGE` and the three `ID_*` selectors
  in `config.py` from that app's `screen.xml`.
