"""Build a Linux/Python 3.13 Lambda ZIP on macOS or Linux, without Docker."""

import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "services/background"
OUTPUT = ROOT / ".artifacts/background-sync.zip"
# Pin the binary artifact as well as the package version.
WHEEL = "pillow-12.3.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
SHA256 = "0847a763afefb695bc912d7c131e7e0632d4edc1d8698f58ddabec8e46b8b6d3"


def build():
    with urllib.request.urlopen("https://pypi.org/pypi/Pillow/12.3.0/json", timeout=30) as response:
        metadata = json.load(response)
    url = next(item["url"] for item in metadata["urls"] if item["filename"] == WHEEL)
    with urllib.request.urlopen(url, timeout=120) as response:
        wheel = response.read()
    if hashlib.sha256(wheel).hexdigest() != SHA256:
        raise ValueError("Pillow wheel checksum mismatch")

    OUTPUT.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        wheel_path = Path(temporary) / WHEEL
        wheel_path.write_bytes(wheel)
        archive_path = Path(temporary) / "background-sync.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            # Stable timestamps/order make repeat builds produce the same ZIP/hash.
            def add(name, data):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)

            add("app.py", (SOURCE / "app.py").read_bytes())
            with zipfile.ZipFile(wheel_path) as dependency:
                for name in sorted(dependency.namelist()):
                    if not name.endswith("/"):
                        add(name, dependency.read(name))
        OUTPUT.write_bytes(archive_path.read_bytes())
    print(f"Built {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
