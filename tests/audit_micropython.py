import os
import re

pico_dir = 'pico_flash'
forbidden_imports = ['datetime', 'typing', 'dataclasses', 'enum', 'abc', 'threading', 'asyncio']
issues = []

for root, dirs, files in os.walk(pico_dir):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                lines = fp.readlines()
                for i, line in enumerate(lines, 1):
                    for imp in forbidden_imports:
                        if re.search(r'\b(import\s+' + imp + r'|from\s+' + imp + r'\s+import)\b', line):
                            issues.append(f'{path}:{i} Forbidden import: {imp}')
                    if '{=' in line or '=}' in line or re.search(r'\{[a-zA-Z0-9_]+\s*=\s*\}', line):
                        issues.append(f'{path}:{i} Debug f-string: {line.strip()}')
                    if 'json.dumps' in line and 'indent' in line:
                        issues.append(f'{path}:{i} json.dumps with indent: {line.strip()}')

if issues:
    print('ISSUES FOUND:')
    for iss in issues:
        print(iss)
else:
    print('ALL PICO_FLASH PYTHON FILES CLEAN OF FORBIDDEN IMPORTS AND PATTERNS!')

