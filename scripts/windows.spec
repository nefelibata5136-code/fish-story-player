# -*- mode: python ; coding: utf-8 -*-
"""Two entry points share one bundled Python runtime and application sources."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
native = root / 'fish_story' / 'vendor' / 'native'
data = collect_data_files('fish_story', include_py_files=True)
data += copy_metadata('mcp', recursive=True)
data += copy_metadata('requests', recursive=True)

analysis = Analysis(
    [str(root / 'scripts' / 'windows_desktop_entry.py'),
     str(root / 'scripts' / 'windows_cli_entry.py')],
    pathex=[str(root), str(native)],
    binaries=[], datas=data,
    hiddenimports=['mcp.server.fastmcp'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pytest', 'tkinter', 'IPython', 'matplotlib', 'numpy'],
    noarchive=False,
    # engine.fingerprint reads its actual source file. Keep source modules
    # outside PYZ so the same engine contract works in source and frozen runs.
    module_collection_mode={'fish_story': 'py'},
)
archive = PYZ(analysis.pure)
entry_names = {'windows_desktop_entry', 'windows_cli_entry'}
runtime_scripts = [item for item in analysis.scripts if item[0] not in entry_names]
desktop_script = next(item for item in analysis.scripts if item[0] == 'windows_desktop_entry')
cli_script = next(item for item in analysis.scripts if item[0] == 'windows_cli_entry')
desktop = EXE(
    archive, [*runtime_scripts, desktop_script], [], exclude_binaries=True,
    name='FishStoryPlayer', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
cli = EXE(
    archive, [*runtime_scripts, cli_script], [], exclude_binaries=True,
    name='fish-story', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
bundle = COLLECT(
    desktop, cli, analysis.binaries, analysis.datas,
    strip=False, upx=False, name='FishStoryPlayer-Windows-x64',
)
