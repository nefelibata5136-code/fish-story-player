"""Import chapters from a user-selected local ZIP without extracting its files.

Only JSON chapter documents enter the private story store. Source code, model
configuration, identity documents and saved games in a repository ZIP are never
copied or executed. This module does not download or redistribute story packs.
"""
from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path

from .service import validate_story


MAX_ARCHIVE_BYTES = 64_000_000
MAX_ARCHIVE_ENTRIES = 10_000
MAX_CHAPTER_BYTES = 20_000_000
MAX_CHAPTER_TOTAL_BYTES = 100_000_000
MAX_COMPRESSION_RATIO = 1000
MAX_CHAPTERS = 100
_PRIVATE_PARTS = frozenset(('core.json', 'core.md', 'core.txt', 'model-config.json',
                            'session.json', 'saves', 'sessions', '.env'))


def _archive_bytes(archive):
    if isinstance(archive, bytes):
        data = archive
    elif isinstance(archive, (str, os.PathLike)):
        with Path(archive).open('rb') as handle:
            data = handle.read(MAX_ARCHIVE_BYTES + 1)
    else:
        raise ValueError('INVALID_STORY_ARCHIVE')
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError('STORY_ARCHIVE_TOO_LARGE')
    return data


def _entries(archive):
    """Reject ambiguous/unsafe member names, even though we never extract them."""
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise ValueError('STORY_ARCHIVE_TOO_LARGE')
    seen = set()
    result = []
    for member in members:
        name = member.orig_filename
        parts = name.rstrip('/').split('/')
        mode = member.external_attr >> 16
        if (not name or name.startswith('/') or '\\' in name or '\x00' in name
                or any(part in ('', '.', '..') or ':' in part for part in parts)
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                or member.flag_bits & 1):
            raise ValueError('STORY_ARCHIVE_UNSAFE')
        normalized = '/'.join(parts).casefold()
        if normalized in seen:
            raise ValueError('STORY_ARCHIVE_AMBIGUOUS')
        seen.add(normalized)
        if (not member.is_dir() and parts[-1].lower().endswith('.json')
                and not any(part.casefold() in _PRIVATE_PARTS for part in parts)):
            result.append((tuple(parts), member))
    return result


def _selected(entries, language):
    # A GitHub source archive has one arbitrary enclosing directory. Match the
    # complete language folder rather than relying on that directory's name.
    groups = {}
    language_folders = False
    for parts, member in entries:
        parent = parts[:-1]
        if len(parent) >= 2 and parent[-2] == '01_json' and parent[-1] in ('zh', 'en'):
            language_folders = True
            if parent[-1] == language:
                groups.setdefault(parent, []).append(member)
    if len(groups) > 1:
        raise ValueError('STORY_ARCHIVE_AMBIGUOUS')
    if groups:
        return next(iter(groups.values()))
    if language_folders:
        raise ValueError('STORY_ARCHIVE_NO_CHAPTERS')

    # A hand-made chapter ZIP may be flat, or contain one enclosing directory.
    # Do not recursively inspect arbitrary source/configuration/saves folders.
    root = [member for parts, member in entries if len(parts) == 1]
    if root:
        return root
    for parts, member in entries:
        if len(parts) == 2:
            groups.setdefault(parts[:-1], []).append(member)
    if len(groups) > 1:
        raise ValueError('STORY_ARCHIVE_AMBIGUOUS')
    if groups:
        return next(iter(groups.values()))
    raise ValueError('STORY_ARCHIVE_NO_CHAPTERS')


def import_story_pack(service, archive: bytes | Path, title='本地故事', language='zh'):
    """Import an entire local source/chapter ZIP with one call.

    ``archive`` is raw uploaded bytes or a local path supplied by the operator.
    For source repositories only ``01_json/<language>/*.json`` is considered;
    ``language`` must be ``zh`` or ``en``. A flat chapter ZIP is also supported.
    Every chapter is validated before ``service.import_story`` can change the
    private store. The return value is that method's usual public story metadata.
    """
    if language not in ('zh', 'en'):
        raise ValueError('INVALID_STORY_LANGUAGE')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValueError('INVALID_STORY_TITLE')
    data = _archive_bytes(archive)
    documents = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            members = _selected(_entries(source), language)
            if len(members) > MAX_CHAPTERS + 20:
                raise ValueError('STORY_ARCHIVE_TOO_LARGE')
            # Check declared sizes before opening the first compressed member.
            for member in members:
                total += member.file_size
                if (member.file_size > MAX_CHAPTER_BYTES or total > MAX_CHAPTER_TOTAL_BYTES
                        or (member.file_size > 0 and member.compress_size == 0)
                        or member.file_size > max(1, member.compress_size) * MAX_COMPRESSION_RATIO):
                    raise ValueError('STORY_ARCHIVE_TOO_LARGE')
                if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('STORY_ARCHIVE_UNSAFE')
            for member in members:
                with source.open(member) as handle:
                    raw = handle.read(MAX_CHAPTER_BYTES + 1)
                if len(raw) > MAX_CHAPTER_BYTES:
                    raise ValueError('STORY_ARCHIVE_TOO_LARGE')
                try:
                    doc = json.loads(raw.decode('utf-8-sig'))
                except ValueError:
                    raise ValueError('INVALID_STORY_ARCHIVE') from None
                if not isinstance(doc, dict) or 'chapter' not in doc:
                    continue  # An optional pack manifest is not a chapter.
                doc = validate_story(doc)
                # Reject non-finite numbers before import_story creates a folder.
                try:
                    serialized = json.dumps(doc, ensure_ascii=False, allow_nan=False)
                except ValueError:
                    raise ValueError('INVALID_STORY_ARCHIVE') from None
                documents.append((doc['chapter']['chapter_number'], serialized))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, UnicodeError, json.JSONDecodeError,
            NotImplementedError, RuntimeError, RecursionError):
        raise ValueError('INVALID_STORY_ARCHIVE') from None
    if not documents:
        raise ValueError('STORY_ARCHIVE_NO_CHAPTERS')
    if len(documents) > MAX_CHAPTERS:
        raise ValueError('STORY_ARCHIVE_TOO_LARGE')
    if len({number for number, _ in documents}) != len(documents):
        raise ValueError('DUPLICATE_CHAPTER')
    with tempfile.TemporaryDirectory(prefix='fish-story-import-') as directory:
        paths = []
        for index, (_, serialized) in enumerate(sorted(documents)):
            path = Path(directory) / f'ch{index:03}.json'
            path.write_text(serialized, encoding='utf-8')
            paths.append(path)
        result = service.import_story(paths, title)
        # An exact pinned archive is also recognized when supplied locally.
        # An arbitrary title/chapter count never establishes Detroit identity.
        import hashlib
        from .source import SOURCE_ID, SOURCE_SHA256, SOURCE_TITLE
        if language == 'zh' and hashlib.sha256(data).hexdigest() == SOURCE_SHA256:
            from .service import read_json, write_json
            from .source import record_local_archive
            manifest_path = service.directory / 'stories' / result['id'] / 'manifest.json'
            manifest = read_json(manifest_path)
            manifest['verified_source_id'] = SOURCE_ID
            manifest['verified_archive_sha256'] = SOURCE_SHA256
            manifest['title'] = SOURCE_TITLE
            write_json(manifest_path, manifest)
            record_local_archive(service, manifest_path, data)
            result['title'] = SOURCE_TITLE
            result.update(is_detroit=True, is_demo=False)
        return result
