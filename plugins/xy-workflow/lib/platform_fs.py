"""Explicit filesystem backend selection; importing it never changes stdlib os."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

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
    os.link(source, target, follow_symlinks=False)
    os.unlink(source)
