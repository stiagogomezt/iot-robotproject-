import os
import zipfile

zip_path = os.path.join("ENTREGA_FINAL", "Entrega_Robot35_2026-11-09.zip")
folders_to_include = ["pico_flash", "flet_app", "common", "docs", "pruebas_thonny", "tests"]
root_files_to_include = ["INICIAR_CENTRO_DE_CONTROL.bat", "README.md", "WORKFLOW.md"]

exclude_patterns = [".env", ".venv", "venv", "__pycache__", ".mpy", ".pyc", "respaldo_pico", ".git", ".pytest_cache"]

def is_excluded(path):
    p_lower = path.lower()
    for ex in exclude_patterns:
        if ex in p_lower:
            return True
    return False

if os.path.exists(zip_path):
    os.remove(zip_path)

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    # 1. Include folders
    for fldr in folders_to_include:
        if os.path.exists(fldr):
            for root, dirs, files in os.walk(fldr):
                for f in files:
                    full_p = os.path.join(root, f)
                    if not is_excluded(full_p):
                        rel_p = os.path.relpath(full_p, ".")
                        zf.write(full_p, rel_p)

    # 2. Include ENTREGA_FINAL markdown docs
    if os.path.exists("ENTREGA_FINAL"):
        for f in os.listdir("ENTREGA_FINAL"):
            if f.endswith(".md"):
                full_p = os.path.join("ENTREGA_FINAL", f)
                rel_p = os.path.join("ENTREGA_FINAL", f)
                zf.write(full_p, rel_p)

    # 3. Include root files
    for rf in root_files_to_include:
        if os.path.exists(rf):
            zf.write(rf, rf)

print(f"✅ ZIP creado exitosamente en: {zip_path}")
print(f"Tamaño: {os.path.getsize(zip_path)} bytes")

with zipfile.ZipFile(zip_path, 'r') as zf:
    namelist = zf.namelist()
    print(f"Total de archivos en ZIP: {len(namelist)}")
    for name in sorted(namelist):
        print(f"  - {name}")
