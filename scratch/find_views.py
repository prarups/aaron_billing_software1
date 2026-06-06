with open(r"f:\antigravity\aaron_billing_software\core\views.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "def product_create" in line:
        print(f"Found def product_create on line {idx + 1}")
    if "def product_update" in line:
        print(f"Found def product_update on line {idx + 1}")
