"""A killed POSIX zombie may retain a PID until the container's init reaps it.
Timeout tests must reject executing children, without requiring control of PID 1.
AccessDenied is treated as alive, never used to turn a failure into a pass.
"""
import psutil


def process_is_executing(pid):
    try:
        return psutil.Process(pid).status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True
