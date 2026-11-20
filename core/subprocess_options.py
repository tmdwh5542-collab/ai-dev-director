"""Captured background jobs must not allocate a new console for every UI poll on Windows."""
import subprocess
import sys


def hidden_console():
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)} if sys.platform == 'win32' else {}
