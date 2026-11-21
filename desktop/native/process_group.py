"""Own a Windows preparation worker and every decoder or model process it starts."""
import ctypes
from ctypes import wintypes


class Limits(ctypes.Structure):
    _fields_ = [("perProcess", ctypes.c_int64), ("perJob", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minWorkingSet", ctypes.c_size_t),
                ("maxWorkingSet", ctypes.c_size_t), ("processLimit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", Limits), ("ioCounters", ctypes.c_uint64 * 6),
                ("memoryLimitsAndPeaks", ctypes.c_size_t * 4)]


class ProcessGroup:
    def __init__(self, process):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.close_handle = kernel.CloseHandle
        self.close_handle.argtypes = [wintypes.HANDLE]
        create = kernel.CreateJobObjectW
        create.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        self.handle = create(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configure = kernel.SetInformationJobObject
        configure.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        assign = kernel.AssignProcessToJobObject
        assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not configure(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not assign(self.handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def close(self):
        if self.handle:
            self.close_handle(self.handle)
            self.handle = None
