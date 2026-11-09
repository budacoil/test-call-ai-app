"""Download the exact original release for analysis; never execute it."""
import hashlib
from pathlib import Path
import sys
import urllib.request

URL = "https://github.com/ppkk12/fortnite-automatic-lap/releases/download/v2.0.0/pk-auto.exe"
EXPECTED = "988953c55ac2a9111eda53c896ea1ba630db3ceb23ec2ccaf4d267b0357e26d4"
TARGET = Path(__file__).resolve().parents[1] / "fortnite-analysis/downloads/pk-auto-v2.0.0.exe"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists() and sha256(TARGET) == EXPECTED:
        print("Already present and verified:", TARGET)
        return
    temporary = TARGET.with_suffix(".download")
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "SpritePilot-transfer"})
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as stream:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                stream.write(block)
        if sha256(temporary) != EXPECTED:
            raise ValueError("SHA-256 mismatch: the downloaded file is not the investigated release")
        temporary.replace(TARGET)
        print("Downloaded and verified (not executed):", TARGET)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
