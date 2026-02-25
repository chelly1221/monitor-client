"""
USB HID Relay Controller — Multi-Device Support

This module provides an async interface to USB HID relay devices.
Automatically detects and manages ALL connected relay devices with
the same VID/PID (16c0:05df). Commands are broadcast to all devices.

Key API patterns from reference code:
- Channel numbering: 1-8 (NOT 0-indexed)
- Special value 255 = ALL channels
- Return values: 0=success, 1=error, 2=out of range

HID Protocol Note:
The reference Windows DLL abstracts the actual HID protocol. This implementation
uses the common DCTTECH/USBRelay protocol which is compatible with most
USB HID relays (VID:16c0, PID:05df).
"""

import asyncio
import logging
import re
from typing import Optional, Dict, List

import hid

logger = logging.getLogger(__name__)


class USBRelayError(Exception):
    """Base exception for USB relay errors"""
    pass


class DeviceNotFoundError(USBRelayError):
    """Device not found or not connected"""
    pass


class InvalidChannelError(USBRelayError):
    """Invalid channel number"""
    pass


class USBRelayController:
    """
    USB HID Relay Controller — Multi-Device Manager

    Automatically detects and manages all connected USB HID relay devices.
    Commands are broadcast to every connected device simultaneously.
    New devices are auto-detected; disconnected devices are auto-removed.
    """

    # Standard USB HID Relay VID/PID
    VENDOR_ID = 0x16c0
    PRODUCT_ID = 0x05df

    # Special channel value for ALL channels
    ALL_CHANNELS = 255

    # How often to scan for new/removed devices (seconds)
    SCAN_INTERVAL = 3

    def __init__(self, serial_number: Optional[str] = None, num_channels: Optional[int] = None,
                 auto_reconnect: bool = True, reconnect_interval: int = 5):
        """
        Initialize USB Relay Controller

        Args:
            serial_number: Ignored (kept for config compat). All devices are auto-detected.
            num_channels: Override channel count. If None, auto-detected per device.
            auto_reconnect: Enable background device scanning
            reconnect_interval: Seconds between reconnection attempts (initial)
        """
        self._configured_channels = num_channels
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval

        # Multi-device state: keyed by device path (bytes)
        self._devices: Dict[bytes, hid.device] = {}
        self._device_info: Dict[bytes, dict] = {}  # serial, channels, state_cache per device

        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Exponential backoff for when no devices found at all
        self._reconnect_delay = reconnect_interval
        self._max_reconnect_delay = 60

        logger.info("Initialized USB Relay Controller (multi-device mode)")

    @staticmethod
    def _detect_channels(product_string: str) -> int:
        """
        Detect number of channels from the device product string.

        Common product strings: "USBRelay1", "USBRelay2", "USBRelay4", "USBRelay8"
        """
        match = re.search(r'(\d+)$', product_string or '')
        if match:
            count = int(match.group(1))
            if count in (1, 2, 4, 8):
                return count
        return 8

    @property
    def num_channels(self) -> Optional[int]:
        """Max channel count across all connected devices, or configured override."""
        if self._configured_channels is not None:
            return self._configured_channels
        if not self._device_info:
            return None
        return max(info['channels'] for info in self._device_info.values())

    @property
    def is_connected(self) -> bool:
        """True if at least one device is connected"""
        return len(self._devices) > 0

    @property
    def device_count(self) -> int:
        """Number of currently connected devices"""
        return len(self._devices)

    @property
    def serial_number(self) -> Optional[str]:
        """Return first device serial for backward compat, or None."""
        if self._device_info:
            first = next(iter(self._device_info.values()))
            return first.get('serial', None)
        return None

    def _open_device(self, enum_info: dict) -> Optional[bytes]:
        """
        Open a single HID device and register it.

        Args:
            enum_info: Device info dict from hid.enumerate()

        Returns:
            Device path if opened successfully, None otherwise.
        """
        path = enum_info['path']
        if path in self._devices:
            return None  # Already open

        try:
            dev = hid.device()
            dev.open_path(path)

            # Determine serial number
            serial = enum_info.get('serial_number', '')
            if not serial:
                try:
                    serial = dev.get_serial_number_string() or ''
                except Exception:
                    pass
            if not serial:
                try:
                    report = dev.get_feature_report(0x01, 9)
                    if report and len(report) >= 5:
                        serial = bytes(report[:5]).decode('ascii', errors='ignore').strip('\x00')
                except Exception:
                    serial = 'unknown'

            # Determine channel count
            if self._configured_channels is not None:
                channels = self._configured_channels
            else:
                try:
                    product = dev.get_product_string() or ''
                    channels = self._detect_channels(product)
                except Exception:
                    channels = 8

            # Read initial state
            state_cache: Dict[int, bool] = {}
            try:
                report = dev.get_feature_report(0x01, 9)
                if report and len(report) >= 8:
                    state_byte = report[7]
                    for ch in range(1, channels + 1):
                        state_cache[ch] = bool(state_byte & (1 << (ch - 1)))
            except Exception:
                pass

            self._devices[path] = dev
            self._device_info[path] = {
                'serial': serial,
                'channels': channels,
                'state_cache': state_cache,
            }

            logger.info(f"Opened device: serial={serial}, channels={channels}, path={path}")
            return path

        except Exception as e:
            logger.error(f"Failed to open device at {path}: {e}")
            return None

    def _close_device(self, path: bytes) -> None:
        """Close and unregister a single device."""
        dev = self._devices.pop(path, None)
        self._device_info.pop(path, None)
        if dev:
            try:
                dev.close()
            except Exception:
                pass

    async def connect(self) -> bool:
        """
        Scan for and connect to all USB relay devices.

        Returns:
            bool: True if at least one device connected
        Raises:
            DeviceNotFoundError: If no devices found
        """
        async with self._lock:
            enum_list = hid.enumerate(self.VENDOR_ID, self.PRODUCT_ID)

            if not enum_list:
                raise DeviceNotFoundError(
                    f"No USB relay devices found (VID:{self.VENDOR_ID:04x}, PID:{self.PRODUCT_ID:04x})"
                )

            opened = 0
            for info in enum_list:
                if self._open_device(info) is not None:
                    opened += 1

            if not self._devices:
                raise DeviceNotFoundError("Found devices but failed to open any")

            self._reconnect_delay = self.reconnect_interval
            logger.info(f"Connected to {len(self._devices)} device(s) (newly opened: {opened})")
            return True

    async def disconnect(self) -> None:
        """Disconnect from all USB relay devices"""
        async with self._lock:
            paths = list(self._devices.keys())
            for path in paths:
                self._close_device(path)
            logger.info("Disconnected from all USB relay devices")

    def _validate_channel(self, channel: int) -> None:
        """Validate channel number against max channels across all devices."""
        if channel == self.ALL_CHANNELS:
            return
        nc = self.num_channels
        if nc is None:
            raise DeviceNotFoundError("No devices connected")
        if not (1 <= channel <= nc):
            raise InvalidChannelError(
                f"Channel {channel} is invalid. Valid range: 1-{nc} or {self.ALL_CHANNELS} for all"
            )

    async def _send_relay_command(self, channel: int, state: bool) -> bool:
        """
        Send relay control command to ALL connected devices.

        Returns:
            bool: True if at least one device succeeded
        """
        if not self._devices:
            raise DeviceNotFoundError("No devices connected")

        state_byte = 0xFF if state else 0xFD
        report = [0x00, state_byte, channel, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

        any_success = False
        failed_paths: List[bytes] = []

        for path, dev in list(self._devices.items()):
            try:
                dev.send_feature_report(report)
                # Update per-device state cache
                info = self._device_info.get(path)
                if info:
                    info['state_cache'][channel] = state
                any_success = True
            except Exception as e:
                serial = self._device_info.get(path, {}).get('serial', '?')
                logger.error(f"Error sending command to device [{serial}]: {e}")
                failed_paths.append(path)

        # Remove failed devices
        for path in failed_paths:
            serial = self._device_info.get(path, {}).get('serial', '?')
            logger.warning(f"Removing failed device [{serial}]")
            self._close_device(path)

        if any_success:
            await asyncio.sleep(0.05)

        return any_success

    async def open_channel(self, channel: int) -> bool:
        """Open (activate) a relay channel on all devices"""
        async with self._lock:
            self._validate_channel(channel)
            logger.debug(f"Opening channel {channel}")
            return await self._send_relay_command(channel, True)

    async def close_channel(self, channel: int) -> bool:
        """Close (deactivate) a relay channel on all devices"""
        async with self._lock:
            self._validate_channel(channel)
            logger.debug(f"Closing channel {channel}")
            return await self._send_relay_command(channel, False)

    async def open_all_channels(self) -> bool:
        """Open all relay channels on all devices"""
        async with self._lock:
            nc = self.num_channels
            if nc is None:
                raise DeviceNotFoundError("No devices connected")
            logger.debug("Opening all channels")
            success = True
            for ch in range(1, nc + 1):
                if not await self._send_relay_command(ch, True):
                    success = False
            return success

    async def close_all_channels(self) -> bool:
        """Close all relay channels on all devices"""
        async with self._lock:
            nc = self.num_channels
            if nc is None:
                raise DeviceNotFoundError("No devices connected")
            logger.debug("Closing all channels")
            success = True
            for ch in range(1, nc + 1):
                if not await self._send_relay_command(ch, False):
                    success = False
            return success

    async def _update_device_state(self, path: bytes) -> bool:
        """
        Update state cache for a single device by reading its feature report.

        Returns:
            True if successful, False if device is dead.
        """
        dev = self._devices.get(path)
        info = self._device_info.get(path)
        if not dev or not info:
            return False

        try:
            report = dev.get_feature_report(0x01, 9)
            if report and len(report) >= 8:
                state_byte = report[7]
                for ch in range(1, info['channels'] + 1):
                    info['state_cache'][ch] = bool(state_byte & (1 << (ch - 1)))
            return True
        except Exception:
            return False

    async def get_status(self) -> Dict[str, Dict[int, bool]]:
        """
        Get status of all relay channels on all devices.

        Returns:
            Dict mapping device serial to {channel: state} dict.
            Example: {"959BI": {1: True, 2: False}, "ABCDE": {1: False, 2: True}}
        """
        async with self._lock:
            if not self._devices:
                raise DeviceNotFoundError("No devices connected")

            result: Dict[str, Dict[int, bool]] = {}
            failed_paths: List[bytes] = []

            for path in list(self._devices.keys()):
                info = self._device_info.get(path)
                if not info:
                    continue

                if await self._update_device_state(path):
                    result[info['serial']] = dict(info['state_cache'])
                else:
                    failed_paths.append(path)

            for path in failed_paths:
                serial = self._device_info.get(path, {}).get('serial', '?')
                logger.warning(f"Removing unresponsive device [{serial}]")
                self._close_device(path)

            if not result and not self._devices:
                raise DeviceNotFoundError("All devices became unresponsive")

            return result

    async def _monitor_loop(self) -> None:
        """
        Background task: health-check existing devices and scan for new ones.
        Runs every SCAN_INTERVAL seconds.
        """
        while not self._shutdown:
            await asyncio.sleep(self.SCAN_INTERVAL)
            if self._shutdown:
                break

            async with self._lock:
                # 1) Health-check existing devices
                failed_paths: List[bytes] = []
                for path, dev in list(self._devices.items()):
                    try:
                        dev.get_feature_report(0x01, 9)
                    except Exception:
                        failed_paths.append(path)

                for path in failed_paths:
                    serial = self._device_info.get(path, {}).get('serial', '?')
                    logger.warning(f"Device [{serial}] health check failed, removing")
                    self._close_device(path)

                # 2) Scan for new devices
                try:
                    enum_list = hid.enumerate(self.VENDOR_ID, self.PRODUCT_ID)
                    for info in enum_list:
                        if info['path'] not in self._devices:
                            result = self._open_device(info)
                            if result:
                                serial = self._device_info[result]['serial']
                                logger.info(f"New device detected and opened: [{serial}]")
                except Exception as e:
                    logger.debug(f"Device scan error: {e}")

    async def start_monitor(self) -> None:
        """Start the background device monitor task"""
        if self.auto_reconnect and (self._monitor_task is None or self._monitor_task.done()):
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def start_reconnect_monitor(self) -> None:
        """Alias for start_monitor"""
        await self.start_monitor()

    async def shutdown(self) -> None:
        """Shutdown the controller and cleanup resources"""
        logger.info("Shutting down USB relay controller")
        self._shutdown = True

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        await self.disconnect()
