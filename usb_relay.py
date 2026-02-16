"""
USB HID Relay Controller

This module provides an async interface to USB HID relay devices.
Based on the reference USB relay API from the Windows C++ implementation.

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
import time
from typing import Optional, Dict
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
    USB HID Relay Controller

    Provides async interface to control USB HID relay devices.
    Supports 1, 2, 4, or 8 channel relay boards.

    Uses the common DCTTECH/USBRelay HID protocol compatible with
    most USB HID relays using VID:16c0, PID:05df.
    """

    # Standard USB HID Relay VID/PID
    VENDOR_ID = 0x16c0
    PRODUCT_ID = 0x05df

    # Special channel value for ALL channels
    ALL_CHANNELS = 255

    def __init__(self, serial_number: str, num_channels: int = 8,
                 auto_reconnect: bool = True, reconnect_interval: int = 5):
        """
        Initialize USB Relay Controller

        Args:
            serial_number: Device serial number (e.g., "AFED5")
            num_channels: Number of channels (1, 2, 4, or 8)
            auto_reconnect: Enable automatic reconnection
            reconnect_interval: Seconds between reconnection attempts
        """
        self.serial_number = serial_number
        self.num_channels = num_channels
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval

        self._device: Optional[hid.Device] = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Exponential backoff for reconnection
        self._reconnect_delay = reconnect_interval
        self._max_reconnect_delay = 60

        # Cache for current relay state (avoids constant HID queries)
        self._state_cache: Dict[int, bool] = {}

        logger.info(f"Initialized USB Relay Controller for device {serial_number}")

    async def connect(self) -> bool:
        """
        Connect to USB relay device

        Returns:
            bool: True if connected successfully

        Raises:
            DeviceNotFoundError: If device not found
        """
        async with self._lock:
            try:
                # Enumerate HID devices
                devices = hid.enumerate(self.VENDOR_ID, self.PRODUCT_ID)

                if not devices:
                    raise DeviceNotFoundError(
                        f"No USB relay devices found (VID:{self.VENDOR_ID:04x}, PID:{self.PRODUCT_ID:04x})"
                    )

                # Find device by serial number
                device_info = None
                for dev in devices:
                    serial = dev.get('serial_number', '')
                    if serial == self.serial_number:
                        device_info = dev
                        break

                if not device_info:
                    available = [d.get('serial_number', 'Unknown') for d in devices]
                    raise DeviceNotFoundError(
                        f"Device with serial '{self.serial_number}' not found. "
                        f"Available devices: {available}"
                    )

                # Open the device
                self._device = hid.Device(path=device_info['path'])
                self._connected = True
                self._reconnect_delay = self.reconnect_interval  # Reset backoff

                logger.info(f"Connected to USB relay device: {self.serial_number}")

                # Initialize state cache
                await self._update_state_cache()

                return True

            except Exception as e:
                self._connected = False
                logger.error(f"Failed to connect to USB relay: {e}")
                raise

    async def disconnect(self) -> None:
        """Disconnect from USB relay device"""
        async with self._lock:
            if self._device:
                try:
                    self._device.close()
                    logger.info(f"Disconnected from USB relay device: {self.serial_number}")
                except Exception as e:
                    logger.error(f"Error during disconnect: {e}")
                finally:
                    self._device = None
                    self._connected = False
                    self._state_cache.clear()

    def _validate_channel(self, channel: int) -> None:
        """
        Validate channel number

        Args:
            channel: Channel number (1-8 or ALL_CHANNELS)

        Raises:
            InvalidChannelError: If channel is invalid
        """
        if channel == self.ALL_CHANNELS:
            return

        if not (1 <= channel <= self.num_channels):
            raise InvalidChannelError(
                f"Channel {channel} is invalid. "
                f"Valid range: 1-{self.num_channels} or {self.ALL_CHANNELS} for all"
            )

    async def _send_relay_command(self, channel: int, state: bool) -> bool:
        """
        Send relay control command using DCTTECH/USBRelay protocol

        Protocol: 9-byte feature report
        [0] = 0x00 (report ID)
        [1] = state (0xFE=off, 0xFF=on)
        [2] = channel number (1-8)
        [3-8] = 0x00 (padding)

        Args:
            channel: Channel number (1-8)
            state: True=ON/OPEN, False=OFF/CLOSED

        Returns:
            bool: True if successful
        """
        if not self._connected or not self._device:
            raise DeviceNotFoundError("Device not connected")

        try:
            # Build HID feature report (DCTTECH protocol)
            # Report format: [0x00, state_byte, channel, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            state_byte = 0xFF if state else 0xFE
            report = bytes([0x00, state_byte, channel, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

            # Send feature report
            self._device.send_feature_report(report)

            # Small delay for relay to actuate
            await asyncio.sleep(0.05)

            # Update cache
            self._state_cache[channel] = state

            return True

        except Exception as e:
            logger.error(f"Error sending relay command: {e}")
            self._connected = False
            if self.auto_reconnect:
                asyncio.create_task(self._reconnect_loop())
            return False

    async def open_channel(self, channel: int) -> bool:
        """
        Open (activate) a relay channel

        Args:
            channel: Channel number (1-8)

        Returns:
            bool: True if successful
        """
        async with self._lock:
            self._validate_channel(channel)
            logger.debug(f"Opening channel {channel}")
            return await self._send_relay_command(channel, True)

    async def close_channel(self, channel: int) -> bool:
        """
        Close (deactivate) a relay channel

        Args:
            channel: Channel number (1-8)

        Returns:
            bool: True if successful
        """
        async with self._lock:
            self._validate_channel(channel)
            logger.debug(f"Closing channel {channel}")
            return await self._send_relay_command(channel, False)

    async def open_all_channels(self) -> bool:
        """
        Open (activate) all relay channels

        Returns:
            bool: True if successful
        """
        async with self._lock:
            logger.debug("Opening all channels")
            success = True
            for ch in range(1, self.num_channels + 1):
                if not await self._send_relay_command(ch, True):
                    success = False
            return success

    async def close_all_channels(self) -> bool:
        """
        Close (deactivate) all relay channels

        Returns:
            bool: True if successful
        """
        async with self._lock:
            logger.debug("Closing all channels")
            success = True
            for ch in range(1, self.num_channels + 1):
                if not await self._send_relay_command(ch, False):
                    success = False
            return success

    async def _update_state_cache(self) -> None:
        """Update the state cache by reading from device"""
        if not self._connected or not self._device:
            return

        try:
            # Request status using feature report
            # Send: [0x00, 0x00, 0x00, ...]
            # Receive: [channel_states, ...]
            report = self._device.get_feature_report(0x00, 9)

            if report and len(report) > 0:
                # First byte contains relay states as bit field
                state_byte = report[0]

                # Update cache: bit 0 = channel 1, bit 1 = channel 2, etc.
                for ch in range(1, self.num_channels + 1):
                    bit = ch - 1
                    self._state_cache[ch] = bool(state_byte & (1 << bit))

        except Exception as e:
            logger.warning(f"Failed to update state cache: {e}")

    async def get_status(self) -> Dict[int, bool]:
        """
        Get status of all relay channels

        Returns:
            Dict mapping channel number to state (True=open, False=closed)
        """
        async with self._lock:
            if not self._connected or not self._device:
                raise DeviceNotFoundError("Device not connected")

            try:
                # Update cache from device
                await self._update_state_cache()

                # Return copy of cache
                return dict(self._state_cache)

            except Exception as e:
                logger.error(f"Error getting relay status: {e}")
                # Return cached state if available
                return dict(self._state_cache) if self._state_cache else {}

    async def _reconnect_loop(self) -> None:
        """Background task for automatic reconnection"""
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Reconnection already in progress

        self._reconnect_task = asyncio.current_task()

        while self.auto_reconnect and not self._shutdown:
            if self._connected:
                await asyncio.sleep(1)
                continue

            try:
                logger.info(f"Attempting to reconnect (retry in {self._reconnect_delay}s)...")
                await asyncio.sleep(self._reconnect_delay)

                await self.connect()

                if self._connected:
                    logger.info("Reconnected successfully!")
                    self._reconnect_delay = self.reconnect_interval
                    break

            except Exception as e:
                logger.warning(f"Reconnection attempt failed: {e}")
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )

    async def start_reconnect_monitor(self) -> None:
        """Start the reconnection monitor background task"""
        if self.auto_reconnect:
            asyncio.create_task(self._reconnect_loop())

    async def shutdown(self) -> None:
        """Shutdown the controller and cleanup resources"""
        logger.info("Shutting down USB relay controller")
        self._shutdown = True

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Check if device is currently connected"""
        return self._connected
