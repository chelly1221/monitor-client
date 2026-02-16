"""
Command Parser for USB Relay Network Controller

Parses and validates plain text commands received over network.

Supported command format:
- OPEN <channel>      # Open relay channel 1-8
- CLOSE <channel>     # Close relay channel 1-8
- OPEN ALL           # Open all channels
- CLOSE ALL          # Close all channels
- STATUS             # Get status of all channels
- TOGGLE <channel>   # Toggle a specific channel
- HELP               # Show available commands
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Command:
    """Parsed command data structure"""
    action: str  # OPEN, CLOSE, STATUS, TOGGLE, HELP
    target: Optional[str] = None  # channel number, "ALL", or None
    raw_command: str = ""

    @property
    def is_help(self) -> bool:
        return self.action == "HELP"

    @property
    def is_status(self) -> bool:
        return self.action == "STATUS"

    @property
    def is_toggle(self) -> bool:
        return self.action == "TOGGLE"

    @property
    def is_open(self) -> bool:
        return self.action == "OPEN"

    @property
    def is_close(self) -> bool:
        return self.action == "CLOSE"

    @property
    def channel(self) -> Optional[int]:
        """Get channel as integer, or None if ALL or not a channel command"""
        if self.target and self.target.upper() != "ALL":
            try:
                return int(self.target)
            except ValueError:
                return None
        return None

    @property
    def is_all_channels(self) -> bool:
        """Check if command targets all channels"""
        return self.target and self.target.upper() == "ALL"


class CommandParserError(Exception):
    """Base exception for command parsing errors"""
    pass


class InvalidCommandError(CommandParserError):
    """Invalid command syntax"""
    pass


class CommandParser:
    """
    Parser for plain text relay control commands

    Thread-safe and stateless - can be used from multiple connections.
    """

    VALID_ACTIONS = {"OPEN", "CLOSE", "STATUS", "TOGGLE", "HELP"}
    CHANNEL_ACTIONS = {"OPEN", "CLOSE", "TOGGLE"}  # Actions that require a target
    NO_TARGET_ACTIONS = {"STATUS", "HELP"}  # Actions that don't need a target

    HELP_TEXT = """Available Commands:
OPEN <channel>   - Open (activate) relay channel 1-8
CLOSE <channel>  - Close (deactivate) relay channel 1-8
OPEN ALL         - Open all relay channels
CLOSE ALL        - Close all relay channels
STATUS           - Get status of all relay channels
TOGGLE <channel> - Toggle a specific relay channel
HELP             - Show this help message

Examples:
  OPEN 1
  CLOSE 3
  OPEN ALL
  STATUS
"""

    def __init__(self, max_channels: int = 8):
        """
        Initialize command parser

        Args:
            max_channels: Maximum number of channels supported (1, 2, 4, or 8)
        """
        self.max_channels = max_channels

    def parse(self, command_str: str) -> Command:
        """
        Parse a plain text command string

        Args:
            command_str: Raw command string from network client

        Returns:
            Command: Parsed command object

        Raises:
            InvalidCommandError: If command syntax is invalid
        """
        # Clean and normalize input
        command_str = command_str.strip()

        if not command_str:
            raise InvalidCommandError("Empty command")

        # Store raw command for logging
        raw = command_str

        # Split into parts
        parts = command_str.upper().split()

        if not parts:
            raise InvalidCommandError("Empty command")

        action = parts[0]

        # Validate action
        if action not in self.VALID_ACTIONS:
            raise InvalidCommandError(
                f"Unknown action: {action}. Type HELP for available commands."
            )

        # Parse based on action type
        if action in self.NO_TARGET_ACTIONS:
            # STATUS or HELP - no target needed
            if len(parts) > 1:
                logger.warning(f"Extra arguments ignored for {action} command")
            return Command(action=action, target=None, raw_command=raw)

        elif action in self.CHANNEL_ACTIONS:
            # OPEN, CLOSE, TOGGLE - require a target
            if len(parts) < 2:
                raise InvalidCommandError(
                    f"{action} requires a channel number or ALL. Example: {action} 1"
                )

            target = parts[1]

            if len(parts) > 2:
                logger.warning(f"Extra arguments ignored: {' '.join(parts[2:])}")

            return Command(action=action, target=target, raw_command=raw)

        else:
            raise InvalidCommandError(f"Unhandled action: {action}")

    def validate(self, command: Command) -> None:
        """
        Validate a parsed command

        Args:
            command: Parsed command to validate

        Raises:
            InvalidCommandError: If command is invalid
        """
        # No validation needed for HELP or STATUS
        if command.is_help or command.is_status:
            return

        # Validate channel commands
        if command.action in self.CHANNEL_ACTIONS:
            if not command.target:
                raise InvalidCommandError(
                    f"{command.action} requires a channel number or ALL"
                )

            # Check if it's ALL
            if command.is_all_channels:
                return  # ALL is valid

            # Validate channel number
            try:
                channel = int(command.target)
            except ValueError:
                raise InvalidCommandError(
                    f"Invalid channel: {command.target}. "
                    f"Must be a number 1-{self.max_channels} or ALL"
                )

            # Check channel range
            if not (1 <= channel <= self.max_channels):
                raise InvalidCommandError(
                    f"Channel {channel} out of range. "
                    f"Valid range: 1-{self.max_channels}"
                )

    def parse_and_validate(self, command_str: str) -> Command:
        """
        Parse and validate a command in one call

        Args:
            command_str: Raw command string

        Returns:
            Command: Validated command object

        Raises:
            InvalidCommandError: If command is invalid
        """
        command = self.parse(command_str)
        self.validate(command)
        return command

    def format_error(self, error: Exception) -> str:
        """
        Format an error message for network clients

        Args:
            error: Exception that occurred

        Returns:
            str: Formatted error message
        """
        if isinstance(error, InvalidCommandError):
            return f"ERROR: {str(error)}"
        else:
            return f"ERROR: {type(error).__name__}: {str(error)}"

    def get_help(self) -> str:
        """
        Get help text

        Returns:
            str: Help message
        """
        return self.HELP_TEXT
