from __future__ import annotations

import hashlib


def derive_stream_seed(master_seed: int, stream_name: str) -> int:
    """Derive a deterministic child RNG seed from (master_seed, stream_name)."""
    digest = hashlib.sha256(f"{master_seed}:{stream_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)
