"""Fetch the S25 Ultra's NPU runtime from Qualcomm's SDK using ZIP byte ranges."""
import io
from pathlib import Path
import requests
import zipfile

URL = 'https://softwarecenter.qualcomm.com/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/2.45.0.260326/v2.45.0.260326.zip'


class Remote(io.RawIOBase):
    def __init__(self):
        self.client = requests.Session()
        response = self.client.get(URL, headers={'Range': 'bytes=-65536'}, timeout=60)
        response.raise_for_status()
        assert response.status_code == 206
        self.size = int(response.headers['Content-Range'].split('/')[-1])
        self.position = 0

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        return self.position

    def tell(self):
        return self.position

    def read(self, size=-1):
        size = min(size if size >= 0 else self.size, self.size - self.position)
        if size <= 0:
            return b''
        response = self.client.get(URL, headers={'Range': f'bytes={self.position}-{self.position+size-1}'}, timeout=120)
        response.raise_for_status()
        assert response.status_code == 206 and len(response.content) == size
        self.position += size
        return response.content


if __name__ == '__main__':
    output = Path(__file__).parent / 'runtime/arm64-v8a'
    required = {'libGenie.so', 'libQnnHtp.so', 'libQnnHtpPrepare.so', 'libQnnSystem.so',
                'libQnnHtpNetRunExtensions.so', 'libQnnHtpV79Stub.so', 'libQnnHtpV79CalculatorStub.so',
                'libQnnHtpV79Skel.so', 'libQnnModelDlc.so'}
    with zipfile.ZipFile(Remote()) as archive:
        selected = [name for name in archive.namelist() if not name.endswith('/') and
                    Path(name).name in required and
                    ('/lib/aarch64-android/' in name or '/lib/hexagon-v79/unsigned/' in name)]
        assert {Path(name).name for name in selected} == required
        for name in selected:
            destination = output / Path(name).name
            if destination.is_file() and destination.stat().st_size == archive.getinfo(name).file_size:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix('.part')
            temporary.write_bytes(archive.read(name))  # ZipFile verifies each SDK member's CRC.
            temporary.replace(destination)
            print(destination.name, destination.stat().st_size, flush=True)
