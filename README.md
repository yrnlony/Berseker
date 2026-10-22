# Berserker — Mock App Login UI-Test Runner

A fixtures-driven Android UI automation runner built with Python, ADB, and UIAutomator. It runs predefined test fixtures, detects app responses, and records results for review.

## Project files

| File | Purpose |
|---|---|
| `config.py` | Settings, selectors, timeouts, and file paths |
| `adb_client.py` | Android Debug Bridge communication |
| `ui.py` | UI hierarchy inspection and element interaction |
| `result_detector.py` | Classifies detected app responses |
| `runner.py` | Main fixture execution and resume logic |
| `test_stats.py` | Test statistics utilities |
| `requirements.txt` | Python dependencies |
| `results/` | Local execution results, progress, and debug dumps; excluded from Git |
| `fixtures.csv` | Local test fixtures; excluded from Git |

## Requirements

1. Python installed and available in PowerShell.
2. Android Platform Tools (`adb`) installed and available on PATH.
3. An Android device connected and authorized for ADB.
4. Required Python packages installed from `requirements.txt`, if any.

## Running

Run these commands from the project folder in PowerShell:

```powershell
adb devices
py runner.py --dry-run
py runner.py --only CU-01
py runner.py
```

Use `py runner.py --restart` to restart the run from the beginning when supported by the current runner version.

## Configuration

Edit `config.py` to configure the app package, UI selectors, timing, and execution mode.

Keep credentials, fixture data, logs, progress files, and generated results local. Do not commit passwords or other sensitive information to GitHub.

## Version history

This repository tracks the source code and project documentation. Local execution data is intentionally excluded so that code history remains separate from test-run artifacts.
