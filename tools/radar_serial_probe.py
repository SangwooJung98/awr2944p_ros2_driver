#!/usr/bin/env python3
"""Query a TI mmWave CLI without changing its configuration or starting RF."""

import argparse
import datetime
import json
from pathlib import Path
import time

import serial


def collect(port, duration):
    deadline = time.monotonic() + duration
    data = bytearray()
    while time.monotonic() < deadline:
        data.extend(port.read(min(port.in_waiting or 1, 4096)))
        if len(data) >= 65536:
            break
    return {
        "bytes": len(data),
        "text": data.decode("utf-8", errors="replace"),
        "hex": data.hex(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--listen-seconds", type=float, default=1.0)
    parser.add_argument("--passive-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.listen_seconds <= 0:
        parser.error("--listen-seconds must be positive")

    result = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
        "port": args.port,
        "baud": args.baud,
        "records": [],
    }
    port = serial.Serial(
        port=None, baudrate=args.baud, timeout=0.1,
        write_timeout=1, exclusive=True,
    )
    port.dtr = True
    port.rts = False
    port.port = args.port
    try:
        port.open()
        result["records"].append({
            "command": None, **collect(port, args.listen_seconds),
        })
        if not args.passive_only:
            for command in ("", "version", "queryDemoStatus", "help"):
                port.write((command + "\r\n").encode("ascii"))
                port.flush()
                result["records"].append({
                    "command": command, **collect(port, 1.0),
                })
    except (serial.SerialException, OSError) as exc:
        result["error"] = str(exc)
    finally:
        port.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
