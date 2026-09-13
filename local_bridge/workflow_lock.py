"""OS-released lock shared by CLI, Windows tasks, and the local control server."""
from contextlib import contextmanager
import os


@contextmanager
def acquire(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as file:
        file.seek(0,2)
        if not file.tell():
            file.write(b'0');file.flush()
        file.seek(0)
        locked=False
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:
            pass
        try:
            yield locked
        finally:
            if locked:
                file.seek(0)
                if os.name=='nt':
                    msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    fcntl.flock(file.fileno(),fcntl.LOCK_UN)
