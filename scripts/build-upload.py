"""Build the dependency-free Python upload-signing Lambda ZIP."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".artifacts/background-upload.zip"
OUTPUT.parent.mkdir(exist_ok=True)
info = zipfile.ZipInfo("app.py", date_time=(2026, 1, 1, 0, 0, 0))
info.compress_type = zipfile.ZIP_DEFLATED
info.external_attr = 0o100644 << 16
with zipfile.ZipFile(OUTPUT, "w") as archive:
    archive.writestr(info, (ROOT / "services/upload/app.py").read_bytes())
print(f"Built {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")
