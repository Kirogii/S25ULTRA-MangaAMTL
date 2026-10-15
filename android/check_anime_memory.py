"""Run the diagnostic sequentially, with conservative host-monitored memory limits."""
import json
from pathlib import Path
import subprocess
import time

ADB = [r'C:\Users\Admin\AppData\Local\Programs\SideQuest\resources\platform-tools\adb.exe', '-s', 'R5CY53N3X1D']
PACKAGE = 'org.mangaamtl.npucheck'


def limit_reason(pss_kb, available_kb):
    if pss_kb > 2560 * 1024:
        return 'Diagnostic PSS exceeded 2.5 GiB'
    if available_kb < 2560 * 1024:
        return 'Phone available memory fell below 2.5 GiB'


def read(*args):
    return subprocess.check_output(ADB + list(args), timeout=10, stderr=subprocess.DEVNULL).decode()


def main():
    evidence = {'passed': False, 'peak_rss_kb': 0, 'peak_pss_kb': 0, 'minimum_available_kb': None}
    target = Path(__file__).parent / 'evidence/anime-256-memory.json'
    try:
        read('shell', 'am', 'force-stop', PACKAGE)
        read('shell', 'run-as', PACKAGE, 'rm', '-f', 'files/anime-report.json')
        read('shell', 'am', 'start', '-n', PACKAGE + '/.AnimeLamaProbe')
        started = time.monotonic()
        next_update = 0
        seen_process = False
        while time.monotonic() - started < 900:
            try:
                pid = read('shell', 'pidof', PACKAGE).strip()
                seen_process = True
            except subprocess.CalledProcessError:
                if not seen_process and time.monotonic() - started < 5:
                    time.sleep(.2)
                    continue
                raise RuntimeError('Diagnostic process exited before producing its report')
            status = read('shell', 'run-as', PACKAGE, 'cat', '/proc/' + pid + '/status')
            rss = int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmRSS:')))
            rollup = read('shell', 'run-as', PACKAGE, 'cat', '/proc/' + pid + '/smaps_rollup')
            pss = int(next(line.split()[1] for line in rollup.splitlines() if line.startswith('Pss:')))
            memory = read('shell', 'cat', '/proc/meminfo')
            available = int(next(line.split()[1] for line in memory.splitlines() if line.startswith('MemAvailable:')))
            evidence['peak_rss_kb'] = max(evidence['peak_rss_kb'], rss)
            evidence['peak_pss_kb'] = max(evidence['peak_pss_kb'], pss)
            evidence['minimum_available_kb'] = min(evidence['minimum_available_kb'] or available, available)
            reason = limit_reason(pss, available)
            if rss > 3 * 1024 * 1024:
                reason = 'Diagnostic RSS exceeded 3 GiB absolute limit'
            if reason:
                raise RuntimeError(reason)
            try:
                report = json.loads(read('shell', 'run-as', PACKAGE, 'cat', 'files/anime-report.json'))
            except subprocess.CalledProcessError:
                report = None
            if report is not None:
                evidence['report'] = report
                evidence['passed'] = report.get('passed', False)
                break
            if time.monotonic() >= next_update:
                print(f'PSS {pss/1024:.0f} MiB; RSS {rss/1024:.0f} MiB; available {available/1024:.0f} MiB', flush=True)
                next_update = time.monotonic() + 20
            time.sleep(.2)
        else:
            raise TimeoutError('Diagnostic exceeded 15 minutes')
    except Exception as error:
        evidence['error'] = str(error)
    finally:
        subprocess.run(ADB + ['shell', 'am', 'force-stop', PACKAGE], timeout=10, check=False)
        target.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2), flush=True)
    if not evidence['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    assert limit_reason(2560 * 1024 + 1, 4096 * 1024)
    assert limit_reason(100 * 1024, 2560 * 1024 - 1)
    assert limit_reason(2560 * 1024, 2560 * 1024) is None
    main()
