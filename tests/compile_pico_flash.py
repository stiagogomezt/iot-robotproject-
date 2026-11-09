import os
import subprocess
import sys
import tempfile
import shutil

pico_dir = 'pico_flash'
py_files = []
for root, dirs, files in os.walk(pico_dir):
    for f in files:
        if f.endswith('.py'):
            py_files.append(os.path.join(root, f))

py_files.sort()

temp_out_dir = tempfile.mkdtemp(prefix="mpy_cross_build_")
print(f"Directorio temporal para compilación mpy-cross: {temp_out_dir}")
print(f"Total .py files in {pico_dir} to compile: {len(py_files)}\n")

success = 0
failed = 0

try:
    for file_path in py_files:
        rel_path = os.path.relpath(file_path, pico_dir)
        target_mpy = os.path.join(temp_out_dir, os.path.splitext(rel_path)[0] + ".mpy")
        os.makedirs(os.path.dirname(target_mpy), exist_ok=True)

        cmd = [sys.executable, "-m", "mpy_cross", "-o", target_mpy, file_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if res.returncode == 0 and os.path.exists(target_mpy):
            size = os.path.getsize(target_mpy)
            print(f"✅ [OK] {file_path:<35} -> {target_mpy:<50} ({size} bytes)")
            success += 1
        else:
            print(f"❌ [FAIL] {file_path:<35}")
            print("  Stderr:", res.stderr.strip())
            print("  Stdout:", res.stdout.strip())
            failed += 1
finally:
    shutil.rmtree(temp_out_dir, ignore_errors=True)
    print(f"\nDirectorio temporal {temp_out_dir} limpiado.")

print("\n" + "=" * 60)
print(f"Compilación finalizada: {success} exitosos, {failed} fallidos.")
print("=" * 60)
if failed > 0:
    sys.exit(1)
