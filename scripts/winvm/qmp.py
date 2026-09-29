#!/usr/bin/env python3
"""A few QEMU Machine Protocol commands for scripts/winvm.sh. Standard library only.

    qmp.py SOCKET keys ret [ret ...]   press keys (QEMU key names; a-b-c = a chord)
    qmp.py SOCKET type TEXT            type text on a US layout
    qmp.py SOCKET click X Y [W H]      left-click at screen pixel X,Y (screen W x H, default 1280x800)
    qmp.py SOCKET screenshot OUT.png   the VM's screen, as PNG
    qmp.py SOCKET powerdown            ask Windows to shut down (ACPI)
    qmp.py SOCKET status               running / paused / shutdown
"""

import json
import socket
import sys
import time


def _call(sock: socket.socket, reader, command: str, arguments: dict | None = None) -> dict:
    message = {"execute": command}
    if arguments:
        message["arguments"] = arguments
    sock.sendall(json.dumps(message).encode() + b"\n")
    while True:
        reply = json.loads(reader.readline())
        if "event" in reply:
            continue
        if "error" in reply:
            raise SystemExit(f"qmp {command}: {reply['error'].get('desc')}")
        return reply.get("return", {})


_PLAIN = {" ": "spc", "-": "minus", "=": "equal", "[": "bracket_left", "]": "bracket_right",
          ";": "semicolon", "'": "apostrophe", "`": "grave_accent", "\\": "backslash",
          ",": "comma", ".": "dot", "/": "slash", "\n": "ret", "\t": "tab"}
_SHIFTED = {"_": "minus", "+": "equal", "{": "bracket_left", "}": "bracket_right", ":": "semicolon",
            '"': "apostrophe", "~": "grave_accent", "|": "backslash", "<": "comma", ">": "dot",
            "?": "slash", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
            "*": "8", "(": "9", ")": "0"}


def _chord(char: str) -> list[str]:
    if char.isalpha():
        return ["shift", char.lower()] if char.isupper() else [char]
    if char.isdigit():
        return [char]
    if char in _PLAIN:
        return [_PLAIN[char]]
    if char in _SHIFTED:
        return ["shift", _SHIFTED[char]]
    raise SystemExit(f"cannot type {char!r}")


def main() -> None:
    path, action, *rest = sys.argv[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        reader = sock.makefile("r")
        reader.readline()  # greeting
        _call(sock, reader, "qmp_capabilities")
        if action == "keys":
            for key in rest:
                chord = [{"type": "qcode", "data": k} for k in key.split("-")]
                _call(sock, reader, "send-key", {"keys": chord})
        elif action == "type":
            for char in " ".join(rest):
                keys = [{"type": "qcode", "data": k} for k in _chord(char)]
                _call(sock, reader, "send-key", {"keys": keys, "hold-time": 30})
                # Faster than this and Windows drops keys, which is worse
                # than slow: a lost quote leaves PowerShell waiting at >>.
                time.sleep(0.05)
        elif action == "click":
            x, y = int(rest[0]), int(rest[1])
            width, height = (int(rest[2]), int(rest[3])) if len(rest) > 3 else (1280, 800)
            move = [
                {"type": "abs", "data": {"axis": "x", "value": x * 32767 // (width - 1)}},
                {"type": "abs", "data": {"axis": "y", "value": y * 32767 // (height - 1)}},
            ]
            _call(sock, reader, "input-send-event", {"events": move})
            time.sleep(0.1)
            for down in (True, False):
                _call(sock, reader, "input-send-event",
                      {"events": [{"type": "btn", "data": {"down": down, "button": "left"}}]})
                time.sleep(0.05)
        elif action == "screenshot":
            _call(sock, reader, "screendump", {"filename": rest[0], "format": "png"})
        elif action == "powerdown":
            _call(sock, reader, "system_powerdown")
        elif action == "status":
            print(_call(sock, reader, "query-status").get("status"))
        else:
            raise SystemExit(f"unknown action {action}")


if __name__ == "__main__":
    main()
