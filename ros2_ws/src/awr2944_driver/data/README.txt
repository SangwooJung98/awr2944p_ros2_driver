These are deterministic SYNTHETIC examples, not real sensor measurements.

synthetic_uart.bin: 80 SDK-style UART packets, 30 artificial points per frame.
synthetic_points.csv: independently generated expected Cartesian values.
SDK version/temperature fields in these fixtures are simulated metadata.

Regenerate from the repository root:
  python3 tools/generate_sample.py
Verify without changing files:
  python3 tools/generate_sample.py --check
