"""Explicit, bounded acquisition from a pinned third-party story source.

Nothing in this module downloads at import/startup. The operator must explicitly
accept the displayed source terms for every acquire request. Imported chapters
and their provenance remain in the private local store, outside release files.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import requests

from .engine import now
from .import_pack import import_story_pack
from .service import GameService, read_json, write_json


SOURCE_COMMIT = '3c4ae839169df24d8934642037f27d2eb2bca9a2'
SOURCE_URL = ('https://codeload.github.com/Baba88611/detroit-ai-player/zip/'
              + SOURCE_COMMIT)
SOURCE_SHA256 = '3a905317fff035e6ff50193ea14862f727cf7a07aa204c1bcd0244efbab38951'
SOURCE_CHAPTER_COUNT = 32
SOURCE_TITLE = '底特律：变人 · 上游中文剧情'
SOURCE_ID = 'detroit-ai-player-zh-' + SOURCE_COMMIT
MAX_DOWNLOAD_BYTES = 16_000_000
DOWNLOAD_TIMEOUT = (10, 45)
MAX_DOWNLOAD_SECONDS = 120
SOURCE_MATERIALS = {
    'docs/legal/README.md': 'UPSTREAM_LICENSE_SCOPE.md',
    'docs/legal/CC-BY-NC-4.0.txt': 'UPSTREAM_CC-BY-NC-4.0.txt',
    'DISCLAIMER.md': 'UPSTREAM_DISCLAIMER.md',
    'LICENSE': 'UPSTREAM_CODE_LICENSE.txt',
}


def source_info() -> dict:
    """Displayable source information; this function performs no network I/O."""
    return {
        'id': SOURCE_ID, 'title': SOURCE_TITLE,
        'repository': 'https://github.com/Baba88611/detroit-ai-player',
        'source_url': SOURCE_URL, 'commit': SOURCE_COMMIT,
        'archive_sha256': SOURCE_SHA256,
        'author': 'Joey Zhang / Detroit AI Player',
        'license': 'CC BY-NC 4.0',
        'license_url': 'https://creativecommons.org/licenses/by-nc/4.0/',
        'license_scope_url': ('https://github.com/Baba88611/detroit-ai-player/blob/'
                              + SOURCE_COMMIT + '/docs/legal/README.md'),
        'disclaimer_url': ('https://github.com/Baba88611/detroit-ai-player/blob/'
                           + SOURCE_COMMIT + '/DISCLAIMER.md'),
        'third_party_notice': (
            '上游作者将其原创转述与决策树按 CC BY-NC 4.0 提供，仅限非商业用途，须保留署名和许可。'
            '此许可不授予《底特律：变人》原作的剧情、角色、设定或商标权利；'
            '本项目未确认完整原作授权。点击获取将直接从上述上游下载到本机，发行包不包含这些章节。'),
        'chapter_count': SOURCE_CHAPTER_COUNT, 'language': 'zh',
        'requires_explicit_acceptance': True,
    }


@contextmanager
def _acquisition_lock(directory):
    """Serialize local threads/processes without touching game or budget ledgers."""
    database = None
    try:
        database = sqlite3.connect(Path(directory) / 'source-acquisition.sqlite', timeout=0)
        database.execute('CREATE TABLE IF NOT EXISTS acquisition_lock (id INTEGER PRIMARY KEY)')
        database.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError as error:
        if database is not None:
            database.close()
        if getattr(error, 'sqlite_errorcode', None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise ValueError('SOURCE_BUSY') from None
        raise ValueError('SOURCE_STORAGE_FAILED') from None
    try:
        yield
    finally:
        database.rollback()
        database.close()


def _download() -> bytes:
    chunks = []
    total = 0
    started = time.monotonic()
    try:
        # This is the one fixed codeload endpoint, not an arbitrary user URL.
        # Do not follow even a same-site redirect without a separately audited pin.
        with requests.get(SOURCE_URL, stream=True, allow_redirects=False,
                          timeout=DOWNLOAD_TIMEOUT,
                          headers={'Accept': 'application/zip',
                                   'User-Agent': 'FishStoryPlayer-source-acquisition'}) as response:
            if 300 <= response.status_code < 400:
                raise ValueError('SOURCE_REDIRECT_BLOCKED')
            if response.status_code != 200:
                raise ValueError('SOURCE_DOWNLOAD_FAILED')
            length = response.headers.get('Content-Length')
            if length and length.isdecimal() and int(length) > MAX_DOWNLOAD_BYTES:
                raise ValueError('SOURCE_DOWNLOAD_TOO_LARGE')
            for chunk in response.iter_content(chunk_size=65_536):
                if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                    raise ValueError('SOURCE_DOWNLOAD_TIMEOUT')
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError('SOURCE_DOWNLOAD_TOO_LARGE')
                chunks.append(chunk)
    except requests.RequestException:
        # Provider/proxy error strings may contain URLs, authentication or paths.
        raise ValueError('SOURCE_DOWNLOAD_FAILED') from None
    data = b''.join(chunks)
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('SOURCE_HASH_MISMATCH')
    return data


def _chapter_numbers(data):
    """Check the pinned archive before any story-store mutation can happen."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [m for m in archive.infolist()
                       if m.filename.endswith('.json')
                       and tuple(m.filename.split('/')[-3:-1]) == ('01_json', 'zh')]
            if len(members) != SOURCE_CHAPTER_COUNT:
                raise ValueError()
            numbers = [json.loads(archive.read(m).decode('utf-8-sig'))['chapter']['chapter_number']
                       for m in members]
            if (any(type(number) is not int for number in numbers)
                    or sorted(numbers) != list(range(1, SOURCE_CHAPTER_COUNT + 1))):
                raise ValueError()
            return sorted(numbers)
    except (ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile,
            RuntimeError, OSError):
        raise ValueError('SOURCE_CONTENT_INVALID') from None


def _public_story(manifest):
    # Private repair evidence can name unseen nodes, guards and ending keys.
    # Tool setup metadata must not become a source of future-game knowledge.
    provenance = {key: value for key, value in manifest['provenance'].items() if key != 'compatibility'}
    if manifest['provenance'].get('compatibility'):
        compatibility = manifest['provenance']['compatibility']
        provenance['compatibility'] = {'version': compatibility['version'],
                                        'change_count': len(compatibility['changes'])}
    return {**{key: manifest[key] for key in ('id', 'title', 'chapters', 'public_distribution')},
            'source': source_info(), 'provenance': provenance}


def _source_materials(data):
    """Keep the pinned source's exact attribution/license notices beside the pack."""
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for relative, local_name in SOURCE_MATERIALS.items():
                found = [m for m in archive.infolist()
                         if m.filename.split('/', 1)[-1] == relative and not m.is_dir()]
                if len(found) != 1 or found[0].file_size > 200_000:
                    raise ValueError()
                result[local_name] = archive.read(found[0])
    except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, OSError):
        raise ValueError('SOURCE_CONTENT_INVALID') from None
    return result


def record_local_archive(service, manifest_path, data):
    """Preserve exact source notices for a verified, user-supplied Chinese ZIP.

    This is also invoked in the private staging area of online acquisition;
    acquire_detroit subsequently records the actual download/acceptance facts.
    Local import never fabricates consent or fetches anything from the network.
    """
    manifest_path = Path(manifest_path)
    directory = manifest_path.parent
    manifest = read_json(manifest_path)
    materials = _source_materials(data)
    for name, raw in materials.items():
        (directory / name).write_bytes(raw)
    notice = (
        '# 第三方剧情来源\n\n作者：Joey Zhang / Detroit AI Player\n\n'
        f'来源：{source_info()["repository"]}\n\n固定提交：{SOURCE_COMMIT}\n\n'
        f'归档 SHA256：{SOURCE_SHA256}\n\n'
        '作者贡献按 CC BY-NC 4.0 提供，须署名并用于非商业用途。'
        '原作的第三方权利不由此授予。上游原始许可和声明见同目录 UPSTREAM_*。\n\n'
        '文件由用户提供的完整 ZIP 导入；程序不据此声称用户接受过在线获取条款。'
        '哈希匹配的兼容调整、各章与通知文件哈希见本地 manifest.json。\n')
    (directory / 'SOURCE_NOTICE.md').write_text(notice, encoding='utf-8')
    provenance = {'schema_version': 1, 'source_id': SOURCE_ID, 'source_commit': SOURCE_COMMIT,
                  'source_url': SOURCE_URL, 'archive_sha256': SOURCE_SHA256,
                  'archive_size_bytes': len(data), 'acquisition': 'user_supplied_verified_local_archive',
                  'chapter_count': len(manifest['chapters']),
                  'chapter_numbers': [c['chapter_number'] for c in manifest['chapters']],
                  'language': 'zh', 'author': 'Joey Zhang / Detroit AI Player',
                  'license': 'CC BY-NC 4.0', 'license_url': source_info()['license_url'],
                  'source_terms_accepted_at': None,
                  'rights_status': 'Local user-supplied archive; upstream contribution license does not grant original-game rights.',
                  'local_chapter_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                           for p in sorted(directory.glob('ch*.json'))},
                  'local_notice_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                          for name in [*SOURCE_MATERIALS.values(), 'SOURCE_NOTICE.md']},
                  'acquisition_complete': True}
    if manifest.get('compatibility'):
        provenance['compatibility'] = manifest['compatibility']
    manifest['provenance'] = provenance
    write_json(manifest_path, manifest)


def _check_local_files(directory, provenance):
    chapters = provenance.get('local_chapter_sha256')
    if not isinstance(chapters, dict) or len(chapters) != SOURCE_CHAPTER_COUNT:
        raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
    if any(not re.fullmatch(r'ch[0-9]{3}\.json', name) for name in chapters):
        raise ValueError('SOURCE_LOCAL_COPY_CHANGED')
    if {p.name for p in directory.glob('ch*.json')} != set(chapters):
        raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
    notices = provenance.get('local_notice_sha256')
    allowed_notices = {*SOURCE_MATERIALS.values(), 'SOURCE_NOTICE.md'}
    if not isinstance(notices, dict) or set(notices) != allowed_notices:
        raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
    for name, expected in {**chapters, **notices}.items():
        path = directory / name
        if not path.is_file():
            raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
        if (path.is_symlink() or not isinstance(expected, str)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError('SOURCE_LOCAL_COPY_CHANGED')


def _existing_story(service):
    for path in sorted((Path(service.directory) / 'stories').glob('*/manifest.json')):
        manifest = read_json(path)
        provenance = manifest.get('provenance', {})
        if (provenance.get('source_id') != SOURCE_ID
                or provenance.get('source_commit') != SOURCE_COMMIT
                or provenance.get('archive_sha256') != SOURCE_SHA256):
            continue
        chapters = manifest.get('chapters', [])
        if (len(chapters) != SOURCE_CHAPTER_COUNT
                or sorted(c.get('chapter_number', 0) for c in chapters)
                != list(range(1, SOURCE_CHAPTER_COUNT + 1))
                or len(list(path.parent.glob('ch*.json'))) != SOURCE_CHAPTER_COUNT):
            raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
        if provenance.get('acquisition_complete') is not True:
            raise ValueError('SOURCE_LOCAL_COPY_INCOMPLETE')
        _check_local_files(path.parent, provenance)
        return _public_story(manifest)
    return None


def acquire_detroit(service, accepted: bool = False) -> dict:
    """Acquire exactly one pinned Chinese pack after explicit operator consent.

    A repeated request returns the original imported story without downloading or
    copying chapters again. Consent is a strict boolean, not a truthy string.
    This copies no source code and makes no model calls or remote writes.
    """
    if accepted is not True:
        raise ValueError('SOURCE_TERMS_REQUIRED')
    try:
        with _acquisition_lock(service.directory):
            existing = _existing_story(service)
            if existing is not None:
                return existing
            data = _download()
            numbers = _chapter_numbers(data)
            materials = _source_materials(data)
            provenance = {
                'schema_version': 1, 'source_id': SOURCE_ID,
                'acquisition': 'user_requested_direct_upstream_download',
                'source_url': SOURCE_URL, 'source_commit': SOURCE_COMMIT,
                'archive_sha256': hashlib.sha256(data).hexdigest(),
                'archive_size_bytes': len(data), 'chapter_count': len(numbers),
                'chapter_numbers': numbers, 'language': 'zh',
                'author': 'Joey Zhang / Detroit AI Player',
                'license': 'CC BY-NC 4.0',
                'license_url': 'https://creativecommons.org/licenses/by-nc/4.0/',
                'source_terms_accepted_at': now(),
                'chapter_text_modifications': (
                    'The acquisition step does not author narrative text. JSON is parsed and reserialized; '
                    'engine validation may insert a missing empty system_prompt.'),
                'rights_status': 'Upstream author contribution is CC BY-NC 4.0; original-game rights are not granted or confirmed.',
            }
            # Publish only a complete, self-contained private story directory.
            # A failed download/import/notice write leaves existing stories alone.
            with tempfile.TemporaryDirectory(prefix='.source-import-', dir=service.directory) as staging:
                staged_service = GameService(staging)
                story = import_story_pack(staged_service, data, title=SOURCE_TITLE, language='zh')
                staged = Path(staging) / 'stories' / story['id']
                manifest_path = staged / 'manifest.json'
                manifest = read_json(manifest_path)
                if manifest.get('compatibility'):
                    provenance['compatibility'] = manifest['compatibility']
                    provenance['chapter_text_modifications'] += (
                        ' Hash-bound reviewed role attribution and terminal-storyline guards were applied; '
                        'private compatibility.changes records the exact adjustments. Existing authored scenes '
                        'and choices remain; clearly labeled software skip receipts replace unavailable storylines.')
                for name, raw in materials.items():
                    (staged / name).write_bytes(raw)
                notice = (
                    '# 第三方来源与本地导入记录\n\n'
                    '作者：Joey Zhang / Detroit AI Player\n\n'
                    f'来源：{source_info()["repository"]}\n\n'
                    f'固定提交：{SOURCE_COMMIT}\n\n'
                    f'下载：{SOURCE_URL}\n\n'
                    f'原始归档 SHA256：{provenance["archive_sha256"]}\n\n'
                    '作者原创转述与决策树适用 CC BY-NC 4.0（非商业、署名）：'
                    'https://creativecommons.org/licenses/by-nc/4.0/\n\n'
                    '上游许可范围、CC 全文、来源声明和代码许可原文保存在本目录的 UPSTREAM_* 文件。'
                    '代码 MIT 许可不替代剧情数据的许可。\n\n'
                    '此导入不创作新剧情文字。JSON 经解析和重新序列化，校验可能补入缺失的空 '
                    'system_prompt，因此本地文件与上游 JSON 不保证字节相同。'
                    '如命中已审查的章节哈希，补充角色视角、已终止角色线路的条件守卫和明确标注的软件跳过回执；'
                    '保留上游原有场景与选项文字。完整变更清单见本地 manifest.json 的 compatibility。'
                    '逐本地章节与通知文件的哈希见 manifest.json 的 provenance。\n\n'
                    '上游许可仅涵盖许可人有权授予的部分；不授予原游戏的剧情、角色、设定或商标权利。'
                    '本地获取记录不代表原游戏权利方授权。发行包不包含这些章节。\n')
                (staged / 'SOURCE_NOTICE.md').write_text(notice, encoding='utf-8')
                provenance['local_chapter_sha256'] = {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(staged.glob('ch*.json'))}
                provenance['local_notice_sha256'] = {
                    name: hashlib.sha256((staged / name).read_bytes()).hexdigest()
                    for name in [*SOURCE_MATERIALS.values(), 'SOURCE_NOTICE.md']}
                provenance['acquisition_complete'] = True
                manifest['provenance'] = provenance
                manifest['rights_status'] = provenance['rights_status']
                write_json(manifest_path, manifest)
                _check_local_files(staged, provenance)
                target = Path(service.directory) / 'stories' / story['id']
                if target.exists():
                    raise ValueError('SOURCE_STORAGE_FAILED')
                os.rename(staged, target)
                return _public_story(manifest)
    except OSError:
        raise ValueError('SOURCE_STORAGE_FAILED') from None
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('SOURCE_IMPORT_FAILED') from None
