"""Retain a Windows process handle through verification and termination."""
import ctypes

class WindowsProcess:
    """Keep one kernel handle open from identity verification through termination.

    A PID can be recycled between a metadata query and Stop-Process. A retained
    handle always refers to the original process, even if it has since exited.
    """
    def __init__(self, pid, terminate=False):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE, optionally TERMINATE.
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000 | int(terminate), False, pid)
        if not self.handle:
            if ctypes.get_last_error() == 87:
                raise ProcessLookupError(pid)
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = pid

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kernel.CloseHandle(self.handle)

    def metadata(self):
        from ctypes import wintypes
        if self.kernel.WaitForSingleObject(self.handle, 0) == 0:
            raise ProcessLookupError(self.pid)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        created = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        return {"pid": self.pid, "created": created, "executable": path.value}

    def stop(self):
        if self.kernel.WaitForSingleObject(self.handle, 0) == 0:
            return
        if not self.kernel.TerminateProcess(self.handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.kernel.WaitForSingleObject(self.handle, 10000) != 0:
            raise RuntimeError("The model process did not exit within 10 seconds.")


