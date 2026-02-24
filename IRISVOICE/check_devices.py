from backend.audio.pipeline import AudioPipeline

print("Checking available audio devices...")
devices = AudioPipeline.list_devices()

print(f"\nTotal devices found: {len(devices)}")
print("\nInput devices (microphones):")
input_devices = [d for d in devices if d.get("input")]
for i, device in enumerate(input_devices):
    print(f"  {i}: {device['name']} (index: {device['index']})")

print("\nOutput devices (speakers):")
output_devices = [d for d in devices if d.get("output")]
for i, device in enumerate(output_devices):
    print(f"  {i}: {device['name']} (index: {device['index']})")

print("\nAll devices:")
for i, device in enumerate(devices):
    print(f"  {i}: {device['name']} (index: {device['index']}, in: {device['input']}, out: {device['output']})")