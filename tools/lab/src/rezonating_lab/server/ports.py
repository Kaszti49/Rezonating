"""Serial port listing for the device page.

``is_node`` marks a port that is *likely* a Rezonating node: the ESP32-S3's own USB-Serial/JTAG (303A:1001), or
one of the USB-UART bridges our bench boards use (classic ESP32 dev boards: CP210x, CH340, CH9102). A bridge can
also belong to some other gadget, so the flag is a hint for the UI's preselection, not a promise.
"""

from __future__ import annotations

NODE_VID = 0x303A  # Espressif
NODE_PID = 0x1001  # ESP32-S3 USB-Serial/JTAG

# (vid, pid) -> node_kind, in sort order: the native ESP32-S3 port first, then the bench bridges.
NODE_KINDS: dict[tuple[int, int], str] = {
    (NODE_VID, NODE_PID): "esp32s3-usb",
    (0x10C4, 0xEA60): "cp210x",  # Silicon Labs CP2102/CP2104 (ESP32 DevKitC and most bench boards)
    (0x1A86, 0x7523): "ch340",  # WCH CH340
    (0x1A86, 0x55D4): "ch9102",  # WCH CH9102 (newer ESP32 dev boards)
}
_RANK = {kind: i for i, kind in enumerate(NODE_KINDS.values())}


def node_kind(vid: int | None, pid: int | None) -> str | None:
    """The kind of likely node behind ``vid:pid``, or None."""
    if vid is None or pid is None:
        return None
    return NODE_KINDS.get((vid, pid))


def list_serial_ports() -> list[dict]:
    """Serial ports with VID:PID; likely nodes (``is_node``) first, the ESP32-S3 USB-Serial/JTAG before the bridges."""
    from serial.tools import list_ports

    out = []
    for p in list_ports.comports():
        vid, pid = p.vid, p.pid
        kind = node_kind(vid, pid)
        out.append(
            {
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "manufacturer": p.manufacturer,
                "serial_number": p.serial_number,
                "vid_pid": f"{vid:04X}:{pid:04X}" if vid is not None and pid is not None else None,
                "is_node": kind is not None,
                "node_kind": kind,
            }
        )
    out.sort(key=lambda d: (_RANK.get(d["node_kind"], len(_RANK)), _port_order(d["device"])))
    return out


def _port_order(device: str) -> tuple[str, int, str]:
    """COM2 before COM10: split a trailing number off the name."""
    head = device.rstrip("0123456789")
    tail = device[len(head) :]
    return (head, int(tail) if tail else -1, device)
