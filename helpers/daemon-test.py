import daemon
import sys
import os
import signal

def shutdown(signum, frame):  # signum and frame are mandatory
    sys.exit(0)

with daemon.DaemonContext(
        chroot_directory=None,
        working_directory='/home/miband2server/tfm-pypimi',
        pidfile=lockfile.FileLock('/var/run/mb2d.pid'),
        signal_map={
            signal.SIGTERM: shutdown,
            signal.SIGTSTP: shutdown
        }):
    print(os.getcwd())
