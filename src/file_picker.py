"""Open the operating system's file chooser without blocking the terminal UI."""
import asyncio
import sys
from pathlib import Path


MAC_CSV_PICKER = '''
try
    activate
    set selectedFile to choose file with prompt "Choose a CSV file for Ask your data" of type {"public.comma-separated-values-text", "csv"}
    return POSIX path of selectedFile
on error number -128
    return ""
end try
'''


async def choose_csv_file() -> Path | None:
    return await native_picker(MAC_CSV_PICKER)


MAC_EXPORT_PICKER = '''
on run argv
    try
        activate
        set startFolder to POSIX file (item 1 of argv) as alias
        set selectedFolder to choose folder with prompt "Save chat results here (a new folder will be created)" default location startFolder
        return POSIX path of selectedFolder
    on error number -128
        return ""
    end try
end run
'''


async def choose_export_folder(default: Path) -> Path | None:
    start = default.resolve()
    while not start.is_dir() and start != start.parent:
        start = start.parent
    return await native_picker(MAC_EXPORT_PICKER, str(start))


async def native_picker(script: str, *arguments: str) -> Path | None:
    if sys.platform != 'darwin':
        raise RuntimeError('The native file chooser currently requires macOS.')
    try:
        process = await asyncio.create_subprocess_exec(
            '/usr/bin/osascript', '-e', script, *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError('Could not open the macOS file chooser. Please try again.') from exc
    try:
        output, _ = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError('Could not open the macOS file chooser. Please try again.')
    selected = output.decode('utf-8').removesuffix('\n')
    return Path(selected) if selected else None
