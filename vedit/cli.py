"""CLI pentru debug și pentru agenți care au doar terminal.

    vedit asset_add project=demo path=clip.mp4
    vedit cut_silences project=demo asset=a0
    vedit render project=demo preview=false
"""
from __future__ import annotations

import inspect
import sys

from . import mcp_server


def _coerce(val: str, ann) -> object:
    ann = ann if isinstance(ann, str) else getattr(ann, "__name__", "str")
    if ann == "bool":
        return val.lower() in ("1", "true", "yes", "da")
    if ann == "int":
        return int(val)
    if ann == "float":
        return float(val)
    return val


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    tools = {n: f for n, f in vars(mcp_server).items()
             if callable(f) and getattr(f, "__module__", "") == mcp_server.__name__ and hasattr(f, "__wrapped__")}
    if not argv or argv[0] not in tools:
        print("tool-uri:", ", ".join(sorted(tools)))
        sys.exit(1)
    fn = tools[argv[0]]
    params = inspect.signature(fn.__wrapped__).parameters
    kwargs = {}
    for arg in argv[1:]:
        k, _, v = arg.partition("=")
        if k not in params:
            sys.exit(f"parametru necunoscut {k}; acceptă: {', '.join(params)}")
        kwargs[k] = _coerce(v, params[k].annotation)
    print(fn(**kwargs))


if __name__ == "__main__":
    main()
