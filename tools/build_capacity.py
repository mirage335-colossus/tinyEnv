#!/usr/bin/env python3
"""Select compile concurrency; stdout is a single positive job count.

Reserve one usable logical CPU and some available RAM. This is an admission
heuristic, not a per-process memory limit or a prediction of compiler RSS.
Only callers with no explicit job count should use this policy.
Testing uses the same resource admission limits. Parallel parents divide an
inherited worker budget before launching children, so automatic nested work does
not independently claim all available resources.
"""
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys

MIB = 1024 * 1024
MEMORY_PER_JOB = 768 * MIB
WORKER_BUDGET = 'FOUNDATION_WORKER_BUDGET'


def read_text(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return ""


def positive_int(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def cgroup_directories(proc=Path('/proc')):
    """Yield (controllers, leaf-to-mount-root paths), including visible parents."""
    membership_text = read_text(proc / 'self/cgroup')
    mount_text = read_text(proc / 'self/mountinfo')
    if not membership_text.strip() or not mount_text.strip():
        raise ValueError('cgroup visibility unknown')
    memberships = []
    for line in membership_text.splitlines():
        fields = line.split(':', 2)
        if len(fields) == 3:
            memberships.append((set(fields[1].split(',')), fields[2]))
    unescape = lambda text: re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), text)
    found = False
    for line in mount_text.splitlines():
        before, sep, after = line.partition(' - ')
        fields, tail = before.split(), after.split()
        if not sep or len(fields) < 5 or len(tail) < 3 or tail[0] not in ('cgroup', 'cgroup2'):
            continue
        root, mount = Path(unescape(fields[3])), Path(unescape(fields[4]))
        controllers = set(tail[2].split(',')) if tail[0] == 'cgroup' else {''}
        for member_controllers, member in memberships:
            if not controllers.intersection(member_controllers):
                continue
            try:
                relative = Path(member).relative_to(root)
            except ValueError:
                continue
            if '..' in relative.parts:
                continue
            leaf = mount / relative
            found = True
            yield controllers, [leaf, *list(leaf.parents)[:len(relative.parts)]]
    if not found:
        raise ValueError('cgroup mount not visible')


def linux_limits(proc=Path('/proc')):
    """Return quota CPU counts and remaining physical-memory limits (bytes)."""
    cpus, memory = [], []
    for controllers, directories in cgroup_directories(proc):
        for directory in directories:
            if '' in controllers:
                quota = read_text(directory / 'cpu.max').split()
                limits = ['memory.high', 'memory.max']
                usage_name = 'memory.current'
            else:
                quota = [read_text(directory / 'cpu.cfs_quota_us'),
                         read_text(directory / 'cpu.cfs_period_us')] if 'cpu' in controllers else []
                limits = ['memory.limit_in_bytes'] if 'memory' in controllers else []
                usage_name = 'memory.usage_in_bytes'
            if any(part.strip() for part in quota):
                if len(quota) != 2:
                    raise ValueError('unrecognized cgroup CPU quota')
                amount, period = map(positive_int, quota)
                if period is None or (amount is None and quota[0].strip() not in ('max', '-1')):
                    raise ValueError('unrecognized cgroup CPU quota')
                if amount is not None:
                    cpus.append(max(1, amount // period))
            for name in limits:
                # Zero is a real exhausted limit, not missing information.
                value = read_text(directory / name).strip()
                if value in ('', 'max', '-1'):
                    continue
                limit = int(value)
                if 0 <= limit < (1 << 60):  # v1's effectively-unlimited sentinel
                    # A known finite limit without usage is indeterminate, not
                    # permission to use host-wide memory inside a container.
                    usage = int(read_text(directory / usage_name))
                    if usage < 0:
                        raise ValueError('invalid cgroup memory usage')
                    memory.append(max(0, limit - usage))
    return cpus, memory


def windows_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in
            ('total_phys', 'avail_phys', 'total_page', 'avail_page',
             'total_virtual', 'avail_virtual', 'avail_extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return min(status.avail_phys, status.avail_page)
    except (AttributeError, OSError):
        pass
    return None


def macos_memory():
    try:
        output = subprocess.check_output(['/usr/bin/vm_stat'], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    page_size = re.search(r'page size of (\d+) bytes', output)
    pages = dict(re.findall(r'^(Pages [\w ]+):\s+(\d+)\.', output, re.M))
    names = ('Pages free', 'Pages inactive', 'Pages speculative')
    if not page_size or any(name not in pages for name in names):
        return None
    # vm_stat displays free minus speculative. Do not also count purgeable.
    return int(page_size[1]) * sum(int(pages[name]) for name in names)


def available_memory(proc=Path('/proc')):
    if sys.platform == 'win32':
        return windows_memory()
    if sys.platform == 'darwin':
        return macos_memory()
    if sys.platform.startswith('linux'):
        match = re.search(r'^MemAvailable:\s+(\d+)\s+kB$', read_text(proc / 'meminfo'), re.M)
        return int(match[1]) * 1024 if match else None
    return None


def usable_cpus():
    counts = [os.cpu_count() or 1]
    if hasattr(os, 'sched_getaffinity'):
        try:
            counts.append(len(os.sched_getaffinity(0)))
        except OSError:
            pass
    if sys.platform == 'win32' and counts[0] <= 64:
        # Above 64, GetProcessAffinityMask covers only the primary group.
        try:
            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p,
                                                     ctypes.POINTER(ctypes.c_size_t),
                                                     ctypes.POINTER(ctypes.c_size_t)]
            process, system = ctypes.c_size_t(), ctypes.c_size_t()
            if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(),
                                             ctypes.byref(process), ctypes.byref(system)):
                counts.append(bin(process.value).count('1'))
        except (AttributeError, OSError):
            pass
    return max(1, min(counts))


def select_jobs(cpus, memory):
    cpu_jobs = max(1, cpus - 1)
    if memory is None:
        # Unknown RAM must not become an unbounded fan-out on large hosts.
        return min(cpu_jobs, 2)
    reserve = max(256 * MIB, memory // 10)
    return min(cpu_jobs, max(1, (memory - reserve) // MEMORY_PER_JOB))


def worker_budget(environment=None):
    """Read a parent's admission ceiling; malformed ceilings fail closed."""
    value = (os.environ if environment is None else environment).get(WORKER_BUDGET)
    if value is None:
        return None
    if not re.fullmatch(r'[0-9]+', str(value)) or int(value) < 1:
        raise ValueError(WORKER_BUDGET + ' must be a positive integer')
    return int(value)


def default_jobs():
    budget = worker_budget()
    try:
        cpus, memory = usable_cpus(), available_memory()
        if sys.platform.startswith('linux'):
            quotas, headrooms = linux_limits()
            cpus = min([cpus, *quotas])
            if headrooms:
                memory = min(headrooms + ([] if memory is None else [memory]))
        selected = select_jobs(cpus, memory)
    except Exception:
        # Advisory detection must never prevent a build on an unfamiliar OS.
        # Explicit --jobs/--build-jobs remain available for such environments.
        selected = 1
    return min(selected, budget) if budget is not None else selected


def default_test_jobs():
    """Bound independent test workers without bypassing CPU or memory limits."""
    return default_jobs()


def compile_jobs(value=None):
    """Resolve a hosted/local compile limit; automatic selection is per machine."""
    if value is None or value in ("", "auto"):
        return default_jobs()
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)) or int(value) < 1:
        raise ValueError("compile jobs must be auto or a positive integer")
    return int(value)


def test_jobs(value=None):
    """Resolve automatic test admission or an explicit operator override."""
    if value is None or value in ('', 'auto'):
        return default_test_jobs()
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)) or int(value) < 1:
        raise ValueError('test jobs must be auto or a positive integer')
    return int(value)


def worker_environment(environment, workers, *, capacity=None):
    """Divide a parent allowance among concurrent children without mutating it.

    Inherited CMake/CTest settings describe the parent's scope, including an
    automatic count resolved earlier by CI. Scope those settings to each child;
    an explicit child command-line override remains authoritative. ``capacity``
    supplies the parent's already-selected compile/test allowance, superseding
    its raw CMake/CTest environment settings after operator precedence resolves.
    """
    workers = test_jobs(workers)
    available = default_jobs()
    inherited = worker_budget(environment)
    if inherited is not None:
        available = min(available, inherited)
    if capacity is not None:
        available = min(available, compile_jobs(capacity))
    else:
        for key, selector in (('CMAKE_BUILD_PARALLEL_LEVEL', compile_jobs),
                              ('CTEST_PARALLEL_LEVEL', test_jobs)):
            if environment.get(key) not in (None, '', 'auto'):
                available = min(available, selector(environment[key]))
    allowance = max(1, available // workers)
    child = dict(environment)
    child[WORKER_BUDGET] = str(allowance)
    # Direct CMake/CTest descendants also need the inherited admission ceiling.
    child['CMAKE_BUILD_PARALLEL_LEVEL'] = str(allowance)
    child['CTEST_PARALLEL_LEVEL'] = str(allowance)
    return child


if __name__ == '__main__':
    if len(sys.argv) > 2:
        raise SystemExit("usage: build_capacity.py [auto|POSITIVE_JOBS]")
    print(compile_jobs(sys.argv[1] if len(sys.argv) == 2 else None))
