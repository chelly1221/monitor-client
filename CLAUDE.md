# AI-Assisted Development with Claude

This project was developed with assistance from Claude (Anthropic's AI assistant) using Claude Code CLI.

## Development Session

**Date**: February 16, 2026
**Claude Model**: Claude Sonnet 4.5
**Development Tool**: Claude Code CLI (Plan Mode + Implementation)

## Project Requirements

The user requested a simple program to control a USB relay when receiving TCP or UDP messages from the network, with the following specifications:

- **Platform**: DietPi (Debian-based Linux)
- **Deployment**: Docker with docker-compose
- **Language**: Python with asyncio
- **USB Device**: HID USB relay (based on provided Windows C++ reference code)
- **Network**: Both TCP and UDP servers simultaneously
- **Commands**: Plain text format (e.g., "OPEN 1", "CLOSE ALL", "STATUS")
- **Configuration**: YAML file in base directory

## Development Process

### 1. Planning Phase
Claude entered plan mode to:
- Analyze the reference USB relay code (Windows C++ implementation)
- Understand the USB HID relay API patterns
- Research Python libraries for Linux HID device access
- Design the application architecture
- Create a comprehensive implementation plan

Key decisions made during planning:
- Use Python `hidapi` library for USB HID communication
- Use `asyncio` for concurrent TCP/UDP handling
- Implement auto-reconnection for USB device reliability
- Docker containerization for easy deployment
- Plain text command protocol for simplicity

### 2. Implementation Phase
Claude implemented the following components:

#### Core Application
1. **usb_relay.py** - USB HID device controller with:
   - Async device operations
   - Auto-reconnection with exponential backoff
   - Thread-safe operations using asyncio locks
   - Support for 1, 2, 4, or 8 channel relay boards

2. **command_parser.py** - Command parser with:
   - Plain text command parsing (OPEN, CLOSE, STATUS, TOGGLE, HELP)
   - Input validation
   - Channel bounds checking
   - Clear error messages

3. **network_server.py** - Network servers with:
   - Concurrent TCP and UDP servers in single event loop
   - IP whitelist support for security
   - Command routing and execution
   - Connection logging

4. **relay_controller.py** - Main application with:
   - Configuration loading from YAML
   - Component orchestration
   - Logging setup with rotation
   - Signal handling for graceful shutdown

#### Docker Deployment
5. **Dockerfile** - Container image with:
   - Python 3.11 slim base
   - System dependencies for USB HID
   - Non-root user for security
   - Health check

6. **docker-compose.yml** - Service orchestration with:
   - Privileged mode for USB access
   - Port mapping for TCP/UDP
   - Volume mounting for config and logs
   - Auto-restart policy

#### Configuration & Documentation
7. **config.yaml** - Example configuration
8. **requirements.txt** - Python dependencies
9. **.dockerignore** - Build exclusions
10. **README.md** - Comprehensive documentation with:
    - Quick start guide
    - Command reference
    - Usage examples
    - Troubleshooting
    - Architecture overview

## Technical Highlights

### USB HID Communication
- Based on reference code patterns from Windows C++ implementation
- Channel numbering: 1-8 (not 0-indexed) to match hardware API
- Special value 255 for ALL channels
- Status returned as bit field

### Async Architecture
- Single asyncio event loop for all I/O operations
- Non-blocking concurrent TCP and UDP handling
- Efficient use of Python's asyncio primitives
- Proper cleanup and graceful shutdown

### Docker Integration
- Privileged mode for USB device access
- Alternative device mapping option for better security
- Read-only config mounting
- Persistent log storage
- Health checks

### Error Handling
- USB device auto-reconnection with exponential backoff
- Network error recovery
- Input validation and sanitization
- Comprehensive logging

## Reference Materials Analyzed

Claude analyzed the provided reference code:
- **usb_relay_device.h** - USB relay API header file
- **CommandApp_USBRelay.cpp** - Windows command-line application
- **How to use the library.txt** - API usage instructions

Key insights from reference code:
- Device enumeration and serial number matching
- Command codes and return values
- Channel numbering convention
- Status bit field format

## Code Quality

The implementation includes:
- **Type hints** throughout the codebase
- **Docstrings** for all classes and functions
- **Error handling** with custom exception classes
- **Logging** at appropriate levels
- **Configuration validation**
- **Security considerations** (IP whitelist, non-root container)

## Testing Recommendations

The README includes manual testing procedures:
- Docker build and deployment
- TCP command testing with netcat
- UDP command testing with netcat
- USB device reconnection testing
- Container lifecycle testing
- Log verification

## Deployment

The application is ready for deployment on DietPi with:
1. Docker and docker-compose installed
2. USB relay device connected
3. Configuration file updated with device serial number
4. Simple `docker-compose up -d` command

## Future Enhancement Ideas

Documented in README for potential future development:
- Authentication (password/token-based)
- Web dashboard for control
- MQTT integration for home automation
- Scheduling and timer-based control
- Multiple USB relay device support
- WebSocket for real-time status push
- Prometheus metrics endpoint

## Files Generated

Total of 10 files created:
- 4 Python modules (usb_relay.py, command_parser.py, network_server.py, relay_controller.py)
- 3 Docker files (Dockerfile, docker-compose.yml, .dockerignore)
- 3 Configuration/documentation files (config.yaml, requirements.txt, README.md)
- Plus this CLAUDE.md file

## Total Development Time

The entire project from requirements gathering through complete implementation and documentation was completed in a single Claude Code session.

## Claude Code Features Used

- **Plan Mode**: For analyzing requirements and designing architecture
- **Explore Agent**: For examining reference code
- **Plan Agent**: For detailed implementation planning
- **Code Generation**: For implementing all modules
- **Documentation**: For comprehensive README and configuration

---

**Note**: While this project was AI-assisted, all code has been designed to be maintainable, well-documented, and follows Python best practices. The implementation is production-ready for controlling USB HID relay devices via network commands.
