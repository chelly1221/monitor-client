#!/usr/bin/env python3
"""
USB HID Relay Network Controller

Main application entry point that orchestrates the USB relay controller
and network servers (TCP/UDP).

Usage:
    python relay_controller.py [--config config.yaml]
"""

import asyncio
import logging
import signal
import sys
import os
from pathlib import Path
from typing import Optional
import yaml

from usb_relay import USBRelayController, DeviceNotFoundError
from network_server import start_servers


class RelayControllerApp:
    """Main application class"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize application

        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self.config: Optional[dict] = None
        self.relay_controller: Optional[USBRelayController] = None
        self.tcp_server = None
        self.udp_transport = None
        self.udp_protocol = None
        self._shutdown_event = asyncio.Event()

    def load_config(self) -> dict:
        """
        Load configuration from YAML file

        Returns:
            dict: Configuration dictionary

        Raises:
            FileNotFoundError: If config file not found
            yaml.YAMLError: If config file is invalid
        """
        config_file = Path(self.config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        # Validate required fields
        required_fields = ['relay', 'network']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required config field: {field}")

        # Set defaults
        config.setdefault('logging', {})
        config['logging'].setdefault('level', 'INFO')
        config['logging'].setdefault('file', None)

        return config

    def setup_logging(self) -> None:
        """Setup logging based on configuration"""
        log_config = self.config.get('logging', {})
        log_level = getattr(logging, log_config.get('level', 'INFO').upper())

        # Create formatters
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Setup root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # File handler (if configured)
        log_file = log_config.get('file')
        if log_file:
            try:
                # Create log directory if needed
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)

                from logging.handlers import RotatingFileHandler
                max_bytes = log_config.get('max_size_mb', 10) * 1024 * 1024
                backup_count = log_config.get('backup_count', 3)

                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=max_bytes,
                    backupCount=backup_count
                )
                file_handler.setLevel(log_level)
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)

                logging.info(f"Logging to file: {log_file}")
            except Exception as e:
                logging.error(f"Failed to setup file logging: {e}")

    async def initialize_relay(self) -> None:
        """Initialize and connect to USB relay device"""
        relay_config = self.config['relay']

        self.relay_controller = USBRelayController(
            serial_number=relay_config.get('serial_number'),
            num_channels=relay_config.get('channels'),
            auto_reconnect=relay_config.get('auto_reconnect', True),
            reconnect_interval=relay_config.get('reconnect_interval', 5)
        )

        try:
            await self.relay_controller.connect()
        except DeviceNotFoundError as e:
            logging.error(f"USB relay device not found: {e}")
            if self.relay_controller.auto_reconnect:
                logging.info("Auto-reconnect enabled, will retry in background...")
                await self.relay_controller.start_reconnect_monitor()
            else:
                raise

    async def start_network_servers(self) -> None:
        """Start TCP and UDP network servers"""
        self.tcp_server, self.udp_transport, self.udp_protocol = await start_servers(
            self.relay_controller,
            self.config
        )

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        loop = asyncio.get_event_loop()

        def signal_handler(sig):
            logging.info(f"Received signal {sig}, initiating shutdown...")
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    async def shutdown(self) -> None:
        """Graceful shutdown"""
        logging.info("Shutting down relay controller...")

        # Stop network servers
        if self.tcp_server:
            logging.info("Stopping TCP server...")
            await self.tcp_server.stop()

        if self.udp_transport:
            logging.info("Stopping UDP server...")
            self.udp_transport.close()

        # Shutdown relay controller
        if self.relay_controller:
            logging.info("Shutting down USB relay controller...")
            await self.relay_controller.shutdown()

        logging.info("Shutdown complete")

    async def run(self) -> None:
        """Main application loop"""
        try:
            # Load configuration
            logging.info(f"Loading configuration from {self.config_path}")
            self.config = self.load_config()

            # Setup logging
            self.setup_logging()

            logging.info("=" * 60)
            logging.info("USB HID Relay Network Controller")
            logging.info("=" * 60)

            # Initialize USB relay
            logging.info("Initializing USB relay controller...")
            await self.initialize_relay()

            # Start network servers
            logging.info("Starting network servers...")
            await self.start_network_servers()

            # Setup signal handlers
            self.setup_signal_handlers()

            logging.info("Application started successfully")
            logging.info("=" * 60)

            # Wait for shutdown signal
            await self._shutdown_event.wait()

        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received")

        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)

        finally:
            await self.shutdown()


async def main():
    """Entry point"""
    # Parse command line arguments (simple version)
    config_path = "config.yaml"

    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help']:
            print("Usage: python relay_controller.py [--config config.yaml]")
            sys.exit(0)
        elif sys.argv[1] == '--config' and len(sys.argv) > 2:
            config_path = sys.argv[2]

    # Create and run application
    app = RelayControllerApp(config_path)
    await app.run()


if __name__ == "__main__":
    # Run the application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
