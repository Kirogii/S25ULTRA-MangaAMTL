"""Run the NPU probe on an explicitly selected, authorized ADB device."""
import argparse
import json
from pathlib import Path
import subprocess
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--model", help="Relative ONNX path in the probe's private files/models folder")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    package = "org.mangaamtl.npucheck"
    if args.timeout < 1 or args.timeout > 900:
        parser.error("--timeout must be between 1 and 900 seconds")

    def adb(*command, check=True):
        return subprocess.run([args.adb, "-s", args.serial, *command],
                              capture_output=True, text=True, check=check, timeout=30)

    adb("shell", "am", "force-stop", package)
    adb("shell", "run-as", package, "rm", "-f", "files/report.json")
    command = ["shell", "am", "start", "-n", package + "/.MainActivity", "--ez", "run_check", "true"]
    if args.model:
        command += ["--es", "model", args.model]
    adb(*command)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        result = adb("shell", "run-as", package, "cat", "files/report.json", check=False)
        if result.returncode == 0:
            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError:
                time.sleep(1)
                continue
            evidence = Path(__file__).parent / "evidence"
            evidence.mkdir(exist_ok=True)
            name = Path(args.model).stem if args.model else "runtime"
            (evidence / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            raise SystemExit(0 if report.get("passed") is True else 1)
        if adb("shell", "pidof", package, check=False).returncode != 0:
            raise RuntimeError("App process exited before producing a report. Inspect its Android crash log.")
        time.sleep(2)
    adb("shell", "am", "force-stop", package)
    raise TimeoutError(f"NPU check did not finish within {args.timeout} seconds; its process was stopped")


if __name__ == "__main__":
    main()
