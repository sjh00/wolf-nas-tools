"""FileTransferService compatibility shim.

Re-export from app.services.transfer package for backward compatibility.
"""

from app.services.transfer import (
    TRANSFER_SKIP_PREFIX,
    FileTransferService,
    is_soft_transfer_failure,
    is_transfer_skip,
    skip_message,
    strip_skip_prefix,
)

__all__ = [
    "TRANSFER_SKIP_PREFIX",
    "FileTransferService",
    "is_soft_transfer_failure",
    "is_transfer_skip",
    "skip_message",
    "strip_skip_prefix",
]
