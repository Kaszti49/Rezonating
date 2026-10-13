"""Serial port listing for the device page."""

from __future__ import annotations

NODE_VID = 0x303A  # Espressif
NODE_PID = 0x1001  # ESP32-S3 USB-Serial/JTAG


def list_serial_ports() -> list[dict]:
    """Serial ports with VID:PID, a node (303A:1001) listed first and flagged ``is_node``."""
    from serial.tools import list_ports

    out = []
    for p in list_ports.comports():
        vid, pid = p.vid, p.pid
        out.append(
            {
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "manufacturer": p.manufacturer,
                "serial_number": p.serial_number,
                "vid_pid": f"{vid:04X}:{pid:04X}" if vid is not None and pid is not None else None,
                "is_node": vid == NODE_VID and pid == NODE_PID,
            }
        )
    out.sort(key=lambda d: (not d["is_node"], d["device"]))
    return out
