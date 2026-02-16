FROM python:3.11-slim

# Metadata
LABEL maintainer="USB Relay Controller"
LABEL description="USB HID Relay Network Controller for DietPi/Linux"

# Install system dependencies for USB HID
RUN apt-get update && apt-get install -y \
    libhidapi-dev \
    libhidapi-hidraw0 \
    libusb-1.0-0 \
    libudev-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY relay_controller.py usb_relay.py network_server.py command_parser.py ./

# Create non-root user for security
RUN useradd -m -u 1000 relayuser && \
    chown -R relayuser:relayuser /app && \
    mkdir -p /var/log && \
    chown relayuser:relayuser /var/log

# Switch to non-root user
USER relayuser

# Expose TCP and UDP ports
EXPOSE 5000/tcp 5001/udp

# Health check (TCP port)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/5000' || exit 1

# Run the application with unbuffered output
CMD ["python", "-u", "relay_controller.py"]
