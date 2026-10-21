import asyncio
from pathlib import Path

import pytest

from src.file_picker import MAC_CSV_PICKER, choose_csv_file


@pytest.mark.parametrize('output,expected', [(b'/tmp/sales report.csv\n', Path('/tmp/sales report.csv')), (b'\n', None)])
async def test_native_selection_and_cancel(monkeypatch, output, expected):
    class Process:
        returncode = 0
        async def communicate(self):
            return output, b''
    async def spawn(*args, **kwargs):
        assert args == ('/usr/bin/osascript', '-e', MAC_CSV_PICKER)
        assert kwargs['stdin'] == asyncio.subprocess.DEVNULL
        return Process()
    monkeypatch.setattr('src.file_picker.sys.platform', 'darwin')
    monkeypatch.setattr('src.file_picker.asyncio.create_subprocess_exec', spawn)
    assert await choose_csv_file() == expected


async def test_quitting_closes_native_picker(monkeypatch):
    started = asyncio.Event()
    class Process:
        returncode = None
        terminated = False
        async def communicate(self):
            started.set()
            await asyncio.Event().wait()
        def terminate(self):
            self.terminated = True
        async def wait(self):
            self.returncode = -15
    process = Process()
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr('src.file_picker.sys.platform', 'darwin')
    monkeypatch.setattr('src.file_picker.asyncio.create_subprocess_exec', spawn)
    task = asyncio.create_task(choose_csv_file())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated
    assert process.returncode == -15


@pytest.mark.parametrize('output', [b'/tmp/chosen exports/\n', b'\n'])
async def test_export_picker_uses_native_folder_dialog_and_safe_default_argument(monkeypatch, tmp_path, output):
    from src.file_picker import choose_export_folder, MAC_EXPORT_PICKER
    default = tmp_path / 'spaces and "quotes" $(literal)' / 'exports'
    class Process:
        returncode = 0
        async def communicate(self):
            return output, b''
    async def spawn(*args, **kwargs):
        assert args == ('/usr/bin/osascript', '-e', MAC_EXPORT_PICKER, str(tmp_path))
        assert not default.exists()
        return Process()
    monkeypatch.setattr('src.file_picker.sys.platform', 'darwin')
    monkeypatch.setattr('src.file_picker.asyncio.create_subprocess_exec', spawn)
    assert await choose_export_folder(default) == (Path('/tmp/chosen exports') if output.strip() else None)
    assert not default.exists()
