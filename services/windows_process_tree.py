"""Retain Windows process identities before signaling an owned launcher."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time


class WindowsProcessTree:
    """Snapshot descendants and keep handles valid after their launcher exits."""

    def __init__(self, root_pid: int) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handles: list[int] = []
        kernel = self._kernel
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            parents: dict[int, int] = {}
            entry = Entry()
            entry.dwSize = ctypes.sizeof(entry)
            available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while available:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(error)
            # Creation times reject stale parent IDs referring to a newer process.
            root = self._open(root_pid)
            if root is None:
                raise RuntimeError("matrix_launcher_exited_before_tree_capture")
            owned = {root_pid: root[1]}
            while True:
                children = [pid for pid, parent in parents.items() if parent in owned and pid not in owned]
                if not children:
                    break
                added = False
                for pid in children:
                    parent = parents.pop(pid)
                    child = self._open(pid)
                    if child is not None and child[1] >= owned[parent]:
                        owned[pid] = child[1]
                        added = True
                    elif child is not None:
                        self._handles.remove(child[0])
                        kernel.CloseHandle(child[0])
                if not added:
                    break
        except BaseException:
            self.close()
            raise
        finally:
            kernel.CloseHandle(snapshot)

    def _open(self, pid: int) -> tuple[int, int] | None:
        """Open a stable identity; ignore only a process that already exited."""
        handle = self._kernel.OpenProcess(0x100001 | 0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process gone
                return None
            raise ctypes.WinError(error)
        self._handles.append(handle)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self._kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return handle, created

    def wait(self, timeout: float) -> bool:
        """Await every retained identity using one total time budget."""
        deadline = time.monotonic() + timeout
        for handle in self._handles:
            result = self._kernel.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000)))
            if result == 258:
                return False
            if result != 0:
                raise ctypes.WinError(ctypes.get_last_error())
        return True

    def terminate(self) -> None:
        """Force only captured live identities, never resolve their PIDs again."""
        for handle in reversed(self._handles):
            result = self._kernel.WaitForSingleObject(handle, 0)
            if result == 0:
                continue
            if result != 258:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self._kernel.TerminateProcess(handle, 1) and self._kernel.WaitForSingleObject(handle, 0) != 0:
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """Release all retained handles without changing process state."""
        for handle in self._handles:
            self._kernel.CloseHandle(handle)
        self._handles.clear()
