# Model conversion

1. Export an actual ONNX file on the PC:

   `python tools/export_onnx.py`

2. Confirm the K230 model, CanMV version, supported operators, input size and official converter.
3. Convert the verified ONNX with that converter to a real `.kmodel`.
4. Validate using the official K230 camera and YOLO examples before connecting Huian logic.

No `.kmodel` is created in this repository during this preparation stage.
