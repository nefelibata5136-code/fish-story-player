"""Local ZIP import acceptance/security checks using original synthetic stories."""
import copy
import io
import json
import stat
import zipfile

import pytest

from fish_story import import_pack
from fish_story.service import GameService, PACKAGE, read_json


def chapter(number=1, title='原创测试章节'):
    doc = copy.deepcopy(read_json(PACKAGE / 'demo' / 'ch01_fog_letter.json'))
    doc['chapter']['chapter_number'] = number
    doc['chapter']['title_zh'] = title
    return doc


def pack(members):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members:
            # ZipInfo's constructor normalizes Windows separators. Set the raw
            # name afterwards to test a genuinely non-portable ZIP member.
            if '\\' in name or '\x00' in name:
                member = zipfile.ZipInfo('placeholder.json')
                member.filename = member.orig_filename = name
                name = member
            archive.writestr(name, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value)
    return data.getvalue()


def test_whole_repository_chooses_one_language_and_only_chapters(tmp_path):
    service = GameService(tmp_path / 'private')
    data = pack([
        ('project-main/01_json/zh/ch02.json', chapter(2)),
        ('project-main/01_json/en/ch01.json', chapter(1, 'ENGLISH_NOT_SELECTED')),
        ('project-main/01_json/zh/ch01.json', chapter(1)),
        ('project-main/01_json/zh/manifest.json', {'license': 'Synthetic fixture'}),
        ('project-main/run.py', 'raise Exception("MUST_NOT_EXECUTE")'),
        ('project-main/.env', 'PRIVATE_FILE_NOT_COPIED'),
        ('project-main/core.md', 'PRIVATE_CORE_NOT_COPIED'),
        ('project-main/saves/private.json', '{invalid private contents'),
        ('project-main/model-config.json', '{invalid private contents'),
    ])
    result = import_pack.import_story_pack(service, data, '导入测试')
    assert result['title'] == '导入测试'
    assert result['public_distribution'] is False
    assert [row['chapter_number'] for row in result['chapters']] == [1, 2]
    directory = service.directory / 'stories' / result['id']
    assert sorted(path.name for path in directory.iterdir()) == ['ch000.json', 'ch001.json', 'manifest.json']
    combined = ''.join(path.read_text(encoding='utf-8') for path in directory.iterdir())
    assert 'PRIVATE' not in combined and 'ENGLISH_NOT_SELECTED' not in combined
    assert service.start('player', story_id=result['id'])['current']['choices']
    view = service.start('player', story_id=result['id'])
    shared = service.export(view['session_id'], share=True)
    assert shared['share_scope'] == 'activity_counts_only'
    assert not shared['privacy']['contains_story_text']


@pytest.mark.parametrize('prefix', ['', 'chapters/'])
def test_flat_or_single_directory_zip_and_path_input(tmp_path, prefix):
    service = GameService(tmp_path / 'private')
    path = tmp_path / 'chapters.zip'
    path.write_bytes(pack([(prefix + 'second.json', chapter(2)), (prefix + 'first.json', chapter(1)),
                           (prefix + 'core.json', 'PRIVATE_INVALID_JSON_MUST_NOT_BE_READ')]))
    result = import_pack.import_story_pack(service, path)
    assert len(result['chapters']) == 2


def test_explicit_english_and_missing_language(tmp_path):
    data = pack([('repo/01_json/en/ch01.json', chapter(1, 'English fixture'))])
    service = GameService(tmp_path)
    result = import_pack.import_story_pack(service, data, language='en')
    assert result['chapters'][0]['title'] == 'English fixture'
    with pytest.raises(ValueError, match='STORY_ARCHIVE_NO_CHAPTERS'):
        import_pack.import_story_pack(service, data)
    with pytest.raises(ValueError, match='INVALID_STORY_LANGUAGE'):
        import_pack.import_story_pack(service, data, language='anything')


@pytest.mark.parametrize('name', ['../outside.json', '/outside.json', 'C:/outside.json',
                                  'a\\outside.json', 'repo/../outside.json', 'a//outside.json',
                                  'ch01.json\x00ignored'])
def test_unsafe_member_names_never_write(tmp_path, name):
    service = GameService(tmp_path / 'private')
    with pytest.raises(ValueError, match='STORY_ARCHIVE_UNSAFE'):
        import_pack.import_story_pack(service, pack([(name, chapter())]))
    assert len(service.stories()) == 1
    assert not (tmp_path / 'outside.json').exists()


def test_symlink_member_and_multiple_repositories_rejected(tmp_path):
    linked = zipfile.ZipInfo('ch01.json')
    linked.create_system = 3
    linked.external_attr = (stat.S_IFLNK | 0o777) << 16
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr(linked, 'some-local-path')
    service = GameService(tmp_path)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_UNSAFE'):
        import_pack.import_story_pack(service, data.getvalue())
    with pytest.raises(ValueError, match='STORY_ARCHIVE_AMBIGUOUS'):
        import_pack.import_story_pack(service, pack([
            ('one/01_json/zh/ch01.json', chapter()), ('two/01_json/zh/ch02.json', chapter(2))]))


@pytest.mark.parametrize('members,code', [
    ([('ch01.json', chapter()), ('ch02.json', chapter())], 'DUPLICATE_CHAPTER'),
    ([('ch01.json', chapter()), ('broken.json', {'chapter': {'chapter_number': 2}})], 'INVALID_STORY_NODES'),
    ([('ch01.json', '{not-json')], 'INVALID_STORY_ARCHIVE'),
    ([('metadata.json', {'nothing': 'a chapter'})], 'STORY_ARCHIVE_NO_CHAPTERS'),
    ([('one/ch01.json', chapter()), ('two/ch02.json', chapter(2))], 'STORY_ARCHIVE_AMBIGUOUS'),
])
def test_validation_completes_before_private_store_changes(tmp_path, members, code):
    service = GameService(tmp_path)
    with pytest.raises(ValueError, match=code):
        import_pack.import_story_pack(service, pack(members))
    assert len(service.stories()) == 1
    assert list((service.directory / 'stories').iterdir()) == []


def test_nonfinite_numbers_rejected_before_import(tmp_path):
    doc = chapter()
    doc['state']['initial']['invalid_number'] = float('nan')
    service = GameService(tmp_path)
    with pytest.raises(ValueError):
        import_pack.import_story_pack(service, pack([('ch01.json', doc)]))
    assert list((service.directory / 'stories').iterdir()) == []


def test_size_limits_are_checked_before_opening_members(tmp_path, monkeypatch):
    service = GameService(tmp_path)
    data = pack([('ch01.json', chapter())])
    monkeypatch.setattr(import_pack, 'MAX_CHAPTER_BYTES', 100)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_TOO_LARGE'):
        import_pack.import_story_pack(service, data)
    monkeypatch.setattr(import_pack, 'MAX_ARCHIVE_BYTES', 100)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_TOO_LARGE'):
        import_pack.import_story_pack(service, data)
    assert list((service.directory / 'stories').iterdir()) == []


def test_empty_nonzip_and_duplicate_names_are_rejected(tmp_path):
    service = GameService(tmp_path)
    for data in (b'', b'not a zip file'):
        with pytest.raises(ValueError, match='INVALID_STORY_ARCHIVE'):
            import_pack.import_story_pack(service, data)
    with pytest.warns(UserWarning):
        duplicated = pack([('ch01.json', chapter()), ('ch01.json', chapter())])
    with pytest.raises(ValueError, match='STORY_ARCHIVE_AMBIGUOUS'):
        import_pack.import_story_pack(service, duplicated)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_AMBIGUOUS'):
        import_pack.import_story_pack(service, pack([('CH01.json', chapter()), ('ch01.json', chapter(2))]))


def test_entry_count_and_compression_ratio_are_bounded(tmp_path, monkeypatch):
    service = GameService(tmp_path)
    monkeypatch.setattr(import_pack, 'MAX_ARCHIVE_ENTRIES', 1)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_TOO_LARGE'):
        import_pack.import_story_pack(service, pack([('ch01.json', chapter()), ('ch02.json', chapter(2))]))
    monkeypatch.setattr(import_pack, 'MAX_ARCHIVE_ENTRIES', 100)
    monkeypatch.setattr(import_pack, 'MAX_COMPRESSION_RATIO', 1)
    with pytest.raises(ValueError, match='STORY_ARCHIVE_TOO_LARGE'):
        import_pack.import_story_pack(service, pack([('ch01.json', chapter())]))
    assert list((service.directory / 'stories').iterdir()) == []
