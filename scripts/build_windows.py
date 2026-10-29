"""Build an offline Windows bundle from explicitly selected public sources.

Run on Windows x64 after installing the application and PyInstaller 6.22.3.
No runtime home, imported chapters, keys or player records are copied.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
BUNDLE_NAME = 'FishStoryPlayer-Windows-x64'
SECRET = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def dependency_notices(target):
    """Copy installed runtime distribution notices, without installation paths."""
    from packaging.requirements import Requirement

    queue = [('fish-story-player', frozenset()), ('pyinstaller', frozenset())]
    # Include distributions actually detected by Analysis, including optional
    # runtime imports beyond the declared dependency closure.
    package_owners = metadata.packages_distributions()
    analysis_path = ROOT / 'build' / 'windows' / 'windows' / 'Analysis-00.toc'
    if analysis_path.is_file():
        analysis = ast.literal_eval(analysis_path.read_text(encoding='utf-8'))
        for section in analysis:
            if not isinstance(section, list):
                continue
            for item in section:
                if not isinstance(item, tuple) or len(item) != 3 or not isinstance(item[0], str):
                    continue
                for owner in package_owners.get(item[0].split('.')[0], []):
                    queue.append((owner, frozenset()))
    found = {}
    evaluated_extras = {}
    notices = target / 'THIRD_PARTY_LICENSES'
    notices.mkdir(exist_ok=True)
    while queue:
        name, requested_extras = queue.pop()
        distribution = metadata.distribution(name)
        key = re.sub(r'[-_.]+', '-', distribution.metadata['Name']).lower()
        extras = set(requested_extras) | {''}
        if key in found and extras <= evaluated_extras[key]:
            continue
        evaluated_extras.setdefault(key, set()).update(extras)
        if key in found:
            for raw in distribution.requires or []:
                requirement = Requirement(raw)
                if requirement.marker is None or any(requirement.marker.evaluate({'extra': extra}) for extra in extras):
                    queue.append((requirement.name, frozenset(requirement.extras)))
            continue
        found[key] = {
            'name': distribution.metadata['Name'], 'version': distribution.version,
            'license': distribution.metadata.get('License-Expression')
                       or distribution.metadata.get('License') or 'See included notices',
            'source_distribution': f'https://pypi.org/project/{key}/{distribution.version}/#files',
            'project_urls': distribution.metadata.get_all('Project-URL') or [],
        }
        copied = []
        for file in distribution.files or []:
            relative = Path(str(file))
            if any(part == '..' for part in relative.parts):
                continue
            base = relative.name.lower()
            if base.startswith(('license', 'licence', 'copying', 'notice', 'authors')):
                source = Path(distribution.locate_file(file))
                if not source.is_file():
                    continue
                destination = notices / key / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                copied.append(destination.relative_to(target).as_posix())
        found[key]['notices'] = copied
        for raw in distribution.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or any(requirement.marker.evaluate({'extra': extra}) for extra in extras):
                queue.append((requirement.name, frozenset(requirement.extras)))
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime license was not found; inspect the build installation.')
    shutil.copyfile(python_license, notices / 'PYTHON-LICENSE.txt')
    # CPython's top-level LICENSE does not contain every incorporated library
    # notice. Preserve the matching official license appendix as well.
    python_version = '.'.join(str(part) for part in sys.version_info[:3])
    appendix_url = f'https://docs.python.org/release/{python_version}/license.html'
    with urllib.request.urlopen(appendix_url, timeout=45) as response:
        appendix = response.read(2_000_000)
    (notices / 'PYTHON-INCORPORATED-LICENSES.html').write_bytes(appendix)
    (notices / 'DEPENDENCIES.json').write_text(
        json.dumps({'python': sys.version.split()[0],
                    'python_license_appendix': {'source': appendix_url,
                                                'sha256': hashlib.sha256(appendix).hexdigest()},
                    'distributions': sorted(found.values(), key=lambda item: item['name'].lower())},
                   ensure_ascii=False, indent=2), encoding='utf-8')


def audit_bundle(target):
    """Hash the concrete artifact and reject obvious private/runtime material."""
    banned = {'.git', '.venv', 'sessions', 'stories', '01_json', '02_setting',
              '04_execution', 'exports', 'reports', '__pycache__', 'core.txt', 'core.md'}
    files = []
    for path in sorted(target.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(target)
        if relative.as_posix() == 'BUNDLE-MANIFEST.json':
            continue  # A manifest cannot contain its own final digest.
        if any(part.lower() in banned for part in relative.parts):
            raise RuntimeError(f'Excluded runtime/story path in bundle: {relative.as_posix()}')
        if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.key', '.log'} or path.name.startswith('.env'):
            raise RuntimeError(f'Private runtime file in bundle: {relative.as_posix()}')
        if 'fish_story' in relative.parts and path.suffix.lower() == '.json' and 'demo' not in relative.parts:
            raise RuntimeError(f'Unexpected story/config data in bundle: {relative.as_posix()}')
        data = path.read_bytes()
        if path.suffix.lower() in {'.py', '.txt', '.md', '.html', '.json', '.toml', '.cfg'} and SECRET.search(data):
            raise RuntimeError(f'Credential-shaped content in bundle: {relative.as_posix()}')
        files.append({'path': relative.as_posix(), 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()})
    manifest = {'version': metadata.version('fish-story-player'),
                'scope': 'Built runtime and public demo only; no imported stories or private homes.',
                'files': files}
    (target / 'BUNDLE-MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(files)


def verify_app_snapshot(target):
    """Catch concurrent edits or stale incremental data before producing a ZIP."""
    package = ROOT / 'fish_story'
    frozen = target / '_internal' / 'fish_story'
    count = 0
    for source in sorted(package.rglob('*')):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix not in {'.py', '.html', '.json'}:
            continue
        relative = source.relative_to(package)
        bundled = frozen / relative
        if not bundled.is_file() or source.read_bytes() != bundled.read_bytes():
            raise RuntimeError('The source changed during packaging or was not collected: '
                               + relative.as_posix() + '. Rebuild before distributing this candidate.')
        count += 1
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-build', action='store_true', help='Audit and zip an existing bundle')
    parser.add_argument('--incremental', action='store_true', help='Reuse this checkout\'s PyInstaller analysis cache when rebuilding after local source edits')
    args = parser.parse_args(argv)
    if sys.platform != 'win32' or sys.maxsize <= 2 ** 32:
        parser.error('Run this builder with Windows x64 Python.')
    if not args.skip_build:
        clean = [] if args.incremental else ['--clean']
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', *clean,
                        '--distpath', str(DIST), '--workpath', str(ROOT / 'build' / 'windows'),
                        str(ROOT / 'scripts' / 'windows.spec')], cwd=ROOT, check=True)
    target = DIST / BUNDLE_NAME
    if not target.is_dir():
        raise RuntimeError('The expected PyInstaller bundle does not exist.')
    for name in ('LICENSE', 'README.md', 'AGENT_START.md', 'start.cmd'):
        shutil.copyfile(ROOT / name, target / name)
    launcher_scripts = target / 'scripts'
    launcher_scripts.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'scripts' / 'launch_windows.ps1', launcher_scripts / 'launch_windows.ps1')
    documentation = target / 'docs'
    documentation.mkdir(exist_ok=True)
    for source in sorted((ROOT / 'docs').iterdir()):
        if source.is_file() and source.suffix.lower() in {'.md', '.png'}:
            shutil.copyfile(source, documentation / source.name)
    (target / 'START-HERE.txt').write_text(
        '大肥鱼的《底特律：变人》· Windows x64 便携版\n\n'
        '1. 完整解压 ZIP，保留 _internal 文件夹。不要只从压缩包中拖出一个 EXE。\n'
        '2. 双击 FishStoryPlayer.exe，程序会自动打开本机游戏网页。\n'
        '3. 首次使用在网页中准备《底特律》32章。只需一次操作，无需寻找 JSON 或填写文件路径。\n'
        '4. 在“原 Agent 直接游玩”中复制连接配置或安装说明给你的小鱼。\n'
        '   详细说明见 AGENT_START.md；游戏本身不创建替代你的小鱼的模型。\n'
        '5. 游玩时保持启动窗口开启。关闭窗口会停止网页服务，每次选择已自动保存；重开可继续。\n\n'
        '此包自带 Python 与全部运行依赖，不需要安装 Python、Git 或 pip。\n'
        '《底特律》剧情在明确请求后从固定上游直接下载到本机，首次获取需要网络，发行包不包含该剧情。\n'
        '网络获取失败时，可在网页中一次选择整个剧情 ZIP，无需解压和逐章导入。\n'
        '剧情与存档保存在用户目录的 .fish-story-player，放在程序文件夹之外；更换程序包不会清除它们。\n'
        '离线原创演示在高级/测试入口中，供检查运行环境使用。\n\n'
        '如果程序未能启动：确认整个 ZIP 已解压，并把文件夹放到自己的“下载”或“文档”目录。\n'
        '此构件未购买代码签名证书；请核对 SHA256 并使用项目发布页或本次明确提供的本地构件。\n'
        '本地隔离验收不等于已经在另一台从未安装过的 Windows 电脑通过验收。\n\n'
        'Runtime and licensing details\n\n'
        'This build is unsigned. Windows may show an unknown-publisher/SmartScreen notice.\n'
        'Check the published SHA256 and obtain the ZIP from the project release page.\n'
        'No Microsoft code-signing certificate or clean-machine certification is claimed.\n\n'
        'Bundled Python is unmodified; PyInstaller selects and packages runtime modules.\n'
        'Project, demo and upstream engine notices are supplied separately. Runtime dependency\n'
        'notices, Python incorporated licenses and the PyInstaller bootloader exception are\n'
        'preserved in THIRD_PARTY_LICENSES. DEPENDENCIES.json links the unmodified\n'
        'dependency source distributions, including the MPL-licensed certifi bundle.\n'
        'See BUNDLE-MANIFEST.json for file hashes.\n',
        encoding='utf-8')
    # Notepad on older Windows reliably recognizes UTF-8 when the guide has a BOM.
    (target / '开始使用.txt').write_text((target / 'START-HERE.txt').read_text(encoding='utf-8'), encoding='utf-8-sig')
    dependency_notices(target)
    source_files = verify_app_snapshot(target)
    count = audit_bundle(target)
    version = metadata.version('fish-story-player')
    archive = DIST / f'{BUNDLE_NAME}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(target.rglob('*')):
            if file.is_file():
                output.write(file, file.relative_to(DIST))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'artifact': archive.name, 'bytes': archive.stat().st_size,
                      'sha256': digest, 'audited_files': count,
                      'source_files_verified': source_files}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
