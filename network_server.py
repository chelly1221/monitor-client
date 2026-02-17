"""
Network Server for USB Relay Controller

Implements concurrent TCP and UDP servers for receiving relay control commands.
Both servers run in the same asyncio event loop.
"""

import asyncio
import logging
from typing import Optional
from command_parser import CommandParser, Command, InvalidCommandError
from usb_relay import USBRelayController

logger = logging.getLogger(__name__)


class RelayCommandHandler:
    """
    Handles relay commands from network clients

    Shared by both TCP and UDP servers.
    """

    def __init__(self, relay_controller: USBRelayController, parser: CommandParser):
        """
        Initialize command handler

        Args:
            relay_controller: USB relay controller instance
            parser: Command parser instance
        """
        self.relay = relay_controller
        self.parser = parser

    async def handle_command(self, command_str: str, client_addr: str) -> str:
        """
        Process a command and return response

        Args:
            command_str: Raw command string
            client_addr: Client address for logging

        Returns:
            str: Response message
        """
        try:
            # Parse and validate command
            command = self.parser.parse_and_validate(command_str)

            logger.info(f"Command from {client_addr}: {command.raw_command}")

            # Execute command
            response = await self._execute_command(command)
            return response

        except InvalidCommandError as e:
            logger.warning(f"Invalid command from {client_addr}: {e}")
            return self.parser.format_error(e)

        except Exception as e:
            logger.error(f"Error handling command from {client_addr}: {e}", exc_info=True)
            return f"ERROR: Internal server error"

    async def _execute_command(self, command: Command) -> str:
        """
        Execute a parsed and validated command

        Args:
            command: Parsed command

        Returns:
            str: Response message
        """
        # Handle HELP
        if command.is_help:
            return self.parser.get_help()

        # Handle STATUS
        if command.is_status:
            status = await self.relay.get_status()
            if not status:
                return "ERROR: Unable to get relay status"

            # Format status response
            status_parts = [f"CH{ch}={'OPEN' if state else 'CLOSED'}"
                           for ch, state in sorted(status.items())]
            return "STATUS: " + ",".join(status_parts)

        # Handle OPEN
        if command.is_open:
            if command.is_all_channels:
                success = await self.relay.open_all_channels()
                return "OK" if success else "ERROR: Failed to open all channels"
            else:
                channel = command.channel
                success = await self.relay.open_channel(channel)
                return "OK" if success else f"ERROR: Failed to open channel {channel}"

        # Handle CLOSE
        if command.is_close:
            if command.is_all_channels:
                success = await self.relay.close_all_channels()
                return "OK" if success else "ERROR: Failed to close all channels"
            else:
                channel = command.channel
                success = await self.relay.close_channel(channel)
                return "OK" if success else f"ERROR: Failed to close channel {channel}"

        # Handle TOGGLE
        if command.is_toggle:
            channel = command.channel
            if not channel:
                return "ERROR: TOGGLE requires a channel number"

            # Get current status
            status = await self.relay.get_status()
            if channel not in status:
                return f"ERROR: Cannot get status for channel {channel}"

            # Toggle the channel
            current_state = status[channel]
            if current_state:
                # Currently open, so close it
                success = await self.relay.close_channel(channel)
                return "OK" if success else f"ERROR: Failed to close channel {channel}"
            else:
                # Currently closed, so open it
                success = await self.relay.open_channel(channel)
                return "OK" if success else f"ERROR: Failed to open channel {channel}"

        return "ERROR: Unknown command"


class TCPServer:
    """Async TCP server for relay commands"""

    def __init__(self, handler: RelayCommandHandler,
                 host: str = "0.0.0.0", port: int = 5000):
        """
        Initialize TCP server

        Args:
            handler: Command handler instance
            host: Bind host
            port: Bind port
        """
        self.handler = handler
        self.host = host
        self.port = port
        self._server: Optional[asyncio.Server] = None

    async def handle_client(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> None:
        """
        Handle a TCP client connection

        Args:
            reader: Stream reader
            writer: Stream writer
        """
        addr = writer.get_extra_info('peername')
        client_ip = addr[0] if addr else "unknown"
        client_port = addr[1] if addr else 0

        logger.info(f"TCP connection from {client_ip}:{client_port}")

        try:
            # Read command (up to 1KB)
            data = await reader.read(1024)

            if not data:
                return

            # Decode and process command
            command_str = data.decode('utf-8').strip()

            # Handle command
            response = await self.handler.handle_command(command_str, f"{client_ip}:{client_port}")

            # Send response
            writer.write(response.encode('utf-8') + b'\n')
            await writer.drain()

        except Exception as e:
            logger.error(f"Error handling TCP client {client_ip}:{client_port}: {e}")

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.debug(f"TCP connection closed: {client_ip}:{client_port}")

    async def start(self) -> None:
        """Start the TCP server"""
        self._server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )

        logger.info(f"TCP server listening on {self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the TCP server"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("TCP server stopped")


class UDPServer(asyncio.DatagramProtocol):
    """Async UDP server for relay commands"""

    def __init__(self, handler: RelayCommandHandler):
        """
        Initialize UDP server

        Args:
            handler: Command handler instance
        """
        self.handler = handler
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established"""
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """
        Handle received UDP datagram

        Args:
            data: Received data
            addr: Client address (host, port)
        """
        client_ip = addr[0]
        client_port = addr[1]

        logger.debug(f"UDP datagram from {client_ip}:{client_port}")

        try:
            # Decode command
            command_str = data.decode('utf-8').strip()

            # Handle command asynchronously
            asyncio.create_task(self._handle_datagram(command_str, addr))

        except Exception as e:
            logger.error(f"Error processing UDP datagram from {client_ip}:{client_port}: {e}")

    async def _handle_datagram(self, command_str: str, addr: tuple) -> None:
        """
        Handle UDP datagram asynchronously

        Args:
            command_str: Command string
            addr: Client address
        """
        client_addr = f"{addr[0]}:{addr[1]}"

        try:
            # Process command
            response = await self.handler.handle_command(command_str, client_addr)

            # Send response
            if self.transport:
                self.transport.sendto(response.encode('utf-8') + b'\n', addr)

        except Exception as e:
            logger.error(f"Error handling UDP command from {client_addr}: {e}")

    def error_received(self, exc: Exception) -> None:
        """Handle errors"""
        logger.error(f"UDP error: {exc}")

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Handle connection loss"""
        if exc:
            logger.error(f"UDP connection lost: {exc}")


async def start_servers(relay_controller: USBRelayController,
                       config: dict) -> tuple:
    """
    Start both TCP and UDP servers

    Args:
        relay_controller: USB relay controller instance
        config: Configuration dictionary

    Returns:
        tuple: (tcp_server, udp_transport, udp_protocol)
    """
    # Create parser (use detected channel count from the controller)
    parser = CommandParser(max_channels=relay_controller.num_channels)

    # Create command handler
    handler = RelayCommandHandler(relay_controller, parser)

    # Start TCP server
    tcp_server = None
    if config['network']['tcp']['enabled']:
        tcp_server = TCPServer(
            handler,
            host=config['network']['tcp']['host'],
            port=config['network']['tcp']['port']
        )
        await tcp_server.start()

    # Start UDP server
    udp_transport = None
    udp_protocol = None
    if config['network']['udp']['enabled']:
        loop = asyncio.get_event_loop()

        udp_protocol = UDPServer(handler)

        udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: udp_protocol,
            local_addr=(
                config['network']['udp']['host'],
                config['network']['udp']['port']
            )
        )

        logger.info(
            f"UDP server listening on "
            f"{config['network']['udp']['host']}:{config['network']['udp']['port']}"
        )

    return tcp_server, udp_transport, udp_protocol
