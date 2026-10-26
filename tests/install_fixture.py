"""A simulated monitor whose target confirms that everything the installer script started has finished."""

FINISHED = {"settled": True, "waited_seconds": 2, "still_running": [], "left_running": [], "windows_installer_busy": False,
            "tracking": "job object", "software": {"added": [], "removed": [], "changed": []}}


def finished(code, lines=()):
    def monitor(pc, pid, log, ex, progress=None, activity=None):
        if activity is not None:
            activity.update(FINISHED)
        return code, list(lines)
    return monitor
