"""Serial transport: the node's USB-Serial/JTAG port, or any pyserial URL such as ``socket://127.0.0.1:7350``.

The port is opened with DTR and RTS de-asserted: both are set *before* ``open()``, because asserting RTS
resets the ESP32-S3 through the USB-Serial/JTAG reset logic (PROTOCOL.md section 1).
"""

from __future__ import annotations

import time

import serial

from .transport_tcp import TransportClosed


def open_serial(url: str, baudrate: int = 115200) -> serial.SerialBase:
    """Open ``url`` with dtr=False, rts=False set first. The baud rate is ignored by the node."""
    port = serial.serial_for_url(url, do_not_open=True)
    port.baudrate = baudrate
    port.dtr = False
    port.rts = False
    port.timeout = 0  # non-blocking reads; SerialTransport.read waits itself
    port.write_timeout = 5.0
    port.open()
    return port


class SerialTransport:
    POLL_S = 0.002

    def __init__(self, url: str, baudrate: int = 115200) -> None:
        self.url = url
        self._port: serial.SerialBase | None = open_serial(url, baudrate)

    def read(self, timeout_s: float) -> bytes:
        """Bytes available within ``timeout_s`` (empty on timeout). Raises :class:`TransportClosed`."""
        if self._port is None:
            raise TransportClosed("closed")
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                data = self._port.read(65536)
            except (serial.SerialException, OSError) as exc:
                raise TransportClosed(str(exc)) from exc
            if data:
                return data
            if time.monotonic() >= deadline:
                return b""
            time.sleep(self.POLL_S)

    def write(self, data: bytes) -> None:
        if self._port is None:
            raise TransportClosed("closed")
        try:
            self._port.write(data)
            self._port.flush()
        except (serial.SerialException, OSError) as exc:
            raise TransportClosed(str(exc)) from exc

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None

    def __repr__(self) -> str:
        return f"SerialTransport({self.url})"
