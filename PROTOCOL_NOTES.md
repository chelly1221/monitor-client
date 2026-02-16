# USB HID Relay Protocol Implementation Notes

## Issue Discovered

After analyzing the reference code, I discovered that the Windows DLL (`usb_relay_device.dll`) abstracts the actual HID protocol. The DLL source code is not available, so the exact HID command bytes were unknown.

## Reference Code Analysis

From `GuiApp_English.cpp`, the Windows implementation shows:

### Confirmed API Patterns:
- **Channel numbering**: 1-8 (NOT 0-indexed) ✓
- **Status format**: Bit field where `(1<<i) & status` checks channel `i+1` ✓
- **Return values**: 0 = success, 1 = error ✓
- **Device handle**: Integer handle from open operation ✓

### Missing Information:
- Actual HID command bytes (not exposed in reference code)
- Whether to use Output Reports or Feature Reports
- Exact byte sequence format

## Solution: DCTTECH/USBRelay Protocol

Implemented the **DCTTECH/USBRelay protocol**, which is the most common protocol for USB HID relays with VID:16c0, PID:05df.

### HID Feature Report Protocol:

**Set Relay State** (9-byte feature report):
```
[0] = 0x00  (report ID)
[1] = 0xFF  (ON) or 0xFE (OFF)
[2] = channel number (1-8)
[3-8] = 0x00 (padding)
```

**Get Relay Status** (9-byte feature report):
```
Request: get_feature_report(0x00, 9)
Response: [state_byte, ...]
- Bit 0 = Channel 1 state
- Bit 1 = Channel 2 state
- ... etc
- 1 = ON/OPEN, 0 = OFF/CLOSED
```

## Implementation Changes

### usb_relay.py v2 (Fixed):
1. Uses `send_feature_report()` instead of `write()` for commands
2. Uses `get_feature_report()` for status queries
3. Implements DCTTECH 9-byte protocol format
4. Adds state caching to reduce HID queries
5. Properly handles bit-field status format matching reference code

### Key Differences from V1:
- **V1**: Guessed at protocol with simple write() calls
- **V2**: Uses proven DCTTECH protocol with feature reports

## Compatibility

This protocol is compatible with:
- Most USB HID relay boards (VID:16c0, PID:05df)
- DCTTECH relay boards
- Generic Chinese USB relay modules
- Boards using the same chipset as the reference hardware

## Testing Required

When testing with actual hardware:

1. Verify device enumeration works
2. Test single channel ON/OFF
3. Test all channels ON/OFF
4. Verify STATUS command returns correct bit field
5. Test reconnection after device unplug/replug

If the hardware uses a **different protocol variant**, you may need to:
- Try different report IDs
- Adjust byte sequences
- Use output reports instead of feature reports
- Consult hardware-specific documentation

## Alternative Protocols

If DCTTECH protocol doesn't work, other common protocols include:

### lcus-relay variant:
```
Write: [relay_num, state]  # Output report
```

### Tuya variant:
```
[0xA0, channel, state, 0x00, ...]  # Different command prefix
```

## References

- Reference code: `GuiApp_English.cpp` lines 143-292
- Common USB relay protocol: DCTTECH/USBRelay standard
- Python HID library: `hidapi` package
- Hardware VID/PID: 0x16c0:0x05df

## Notes for Future Development

If issues arise with the current protocol:
1. Enable DEBUG logging to see HID communication
2. Use `usbhid` tools on Linux to capture raw HID traffic
3. Compare with Windows DLL behavior using USB monitor tools
4. Consider adding protocol auto-detection or configuration option
