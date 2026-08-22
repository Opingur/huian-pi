# Model conversion

1. Export an actual ONNX file on the PC:

   `python scripts/export_onnx.py`

2. Confirm the target deployment runtime, supported operators, input size and official converter before any conversion.
3. Convert the verified ONNX with that converter to a real `.kmodel`.
4. Validate with the target device camera and YOLO examples before connecting Huian logic.

No `.kmodel` is created in this repository during this preparation stage.
