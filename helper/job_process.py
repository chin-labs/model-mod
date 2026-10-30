"""Conservative process identity checks for background job recovery."""
import os
import signal
import subprocess
import sys


def start_time(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0: return None
    if sys.platform.startswith('linux'):
        try:
            with open('/proc/%d/stat' % pid, encoding='ascii') as source: stat = source.read()
            fields = stat[stat.rfind(')') + 2:].split()
            return 'linux:' + fields[19]
        except (OSError, IndexError): return None
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(['/bin/ps', '-o', 'lstart=', '-p', str(pid)], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, timeout=1, check=False)
            value = result.stdout.strip()
            return 'darwin:' + value if result.returncode == 0 and value else None
        except (OSError, subprocess.TimeoutExpired): return None
    return None


def verified_group(pgid, members):
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 1: return False
    for member in members:
        try:
            pid, started = member['pid'], member['started']
            if not isinstance(started, str) or not started: continue
            if start_time(pid) == started and os.getpgid(pid) == pgid:
                return True
        except (KeyError, TypeError, OSError):
            continue
    return False


def cleanup_verified(pgid, members):
    if not verified_group(pgid, members): return False
    try: os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError: return False
    return True
