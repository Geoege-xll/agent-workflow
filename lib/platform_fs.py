"""Explicit filesystem backend selection; importing it never changes stdlib os."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

if os.name == "nt":
    if __package__:
        from .windows_fs import secure_os as os, directory_lock
    else:
        from windows_fs import secure_os as os, directory_lock
else:
    @contextmanager
    def directory_lock(path, purpose="publication", *, blocking=False):
        import fcntl
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(descriptor, flags)
            yield descriptor
        finally:
            os.close(descriptor)


def publish_exclusive(source: Path, target: Path) -> None:
    """Publish a temporary regular file without replacing a concurrent target."""
    if os.name == "nt":
        os.rename(source, target)
    else:
        os.link(source, target, follow_symlinks=False)
        os.unlink(source)


@contextmanager
def project_install_lock(project: Path):
    """Hold the same project identity until setup writers and recovery finish."""
    with directory_lock(project, "install"):
        if os.name == "nt":
            # Probe metadata durability before creating a stage or any project
            # file. Unsupported filesystem/account capabilities fail closed.
            descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        yield
