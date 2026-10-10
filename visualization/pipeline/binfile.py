"""Write several typed arrays into one little-endian binary file.

The returned descriptor goes into the JSON next to the file, and the browser
opens each array as a typed-array view (see src/loaders/binfile.js).
"""

from array import array
from pathlib import Path
import sys

TYPES = {"uint8": "B", "uint32": "I", "int32": "i", "float32": "f"}


def write_buffers(path: Path, arrays: dict[str, tuple[str, list]]) -> dict:
    descriptor = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as out:
        offset = 0
        for name, (kind, values) in arrays.items():
            data = array(TYPES[kind], values)
            assert data.itemsize in (1, 4), f"{kind} must be 1 or 4 bytes"
            if sys.byteorder != "little":
                data.byteswap()
            raw = data.tobytes()
            descriptor[name] = {"type": kind, "offset": offset, "length": len(data)}
            out.write(raw)
            offset += len(raw)
            padding = -offset % 4  # keep every view 4-byte aligned
            out.write(b"\0" * padding)
            offset += padding
    return descriptor
