"""No-network source acquisition tests using only original synthetic chapters."""
import hashlib
import io
import json
import zipfile

import pytest
import requests

from fish_story import source
from fish_story.service import GameService, read_json


def archive_bytes(chapters=2):
    handle = io.BytesIO()
    with zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for number in range(1, chapters + 1):
            doc = {
                'chapter': {'id': f'original-{number}', 'chapter_number': number, 'title': 'Original synthetic chapter'},
                'nodes': [{'id': 'present', 'type': 'choice', 'player_facing': {
                    'context': 'An original scene', 'choices': [{'id': 'go', 'text': 'Continue'}]}}],
                'endings': {'end': {'title': 'Original ending', 'narrative': 'A synthetic result'}},
            }
            archive.writestr(f'original-source/01_json/zh/ch{number:02}.json',
                             json.dumps(doc).encode())
        archive.writestr('original-source/do-not-run.py', 'raise RuntimeError("MUST_NOT_EXECUTE")')
        archive.writestr('original-source/02_setting/core.md', 'DO_NOT_IMPORT_THIS_CORE')
        for relative in source.SOURCE_MATERIALS:
            archive.writestr('original-source/' + relative, 'Original synthetic source notice: ' + relative)
    return handle.getvalue()


class Response:
    def __init__(self, content, status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        for index in range(0, len(self.content), 97):
            yield self.content[index:index + 97]


@pytest.fixture
def pinned(monkeypatch):
    data = archive_bytes()
    calls = []
    response = Response(data)
    monkeypatch.setattr(source, 'SOURCE_CHAPTER_COUNT', 2)
    monkeypatch.setattr(source, 'SOURCE_SHA256', hashlib.sha256(data).hexdigest())

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(source.requests, 'get', get)
    return data, calls, response


def test_information_and_strict_consent_never_use_network(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('NETWORK_MUST_NOT_RUN')
    monkeypatch.setattr(source.requests, 'get', denied)
    info = source.source_info()
    assert info['author'] == 'Joey Zhang / Detroit AI Player'
    assert info['license'] == 'CC BY-NC 4.0'
    assert info['requires_explicit_acceptance'] is True
    assert info['commit'] in info['source_url']
    service = GameService(tmp_path)
    for accepted in (False, None, 1, 'true', {}, []):
        with pytest.raises(ValueError, match='^SOURCE_TERMS_REQUIRED$'):
            source.acquire_detroit(service, accepted)
    assert not list((tmp_path / 'stories').iterdir())
    assert not (tmp_path / 'source-acquisition.sqlite').exists()


def test_import_provenance_and_idempotent_retry(tmp_path, pinned):
    data, calls, response = pinned
    service = GameService(tmp_path)
    result = source.acquire_detroit(service, True)
    assert len(result['chapters']) == 2
    assert result['public_distribution'] is False
    provenance = result['provenance']
    assert provenance['archive_sha256'] == hashlib.sha256(data).hexdigest()
    assert provenance['archive_size_bytes'] == len(data)
    assert provenance['source_commit'] == source.SOURCE_COMMIT
    assert provenance['chapter_numbers'] == [1, 2]
    assert provenance['source_terms_accepted_at']
    assert 'not granted or confirmed' in provenance['rights_status']
    assert response.closed
    assert len(calls) == 1
    assert calls[0][0] == source.SOURCE_URL
    assert calls[0][1]['allow_redirects'] is False
    assert calls[0][1]['stream'] is True
    assert calls[0][1]['timeout'] == source.DOWNLOAD_TIMEOUT
    assert source.acquire_detroit(GameService(tmp_path), True) == result
    assert len(calls) == 1
    directory = tmp_path / 'stories' / result['id']
    assert len(list((tmp_path / 'stories').iterdir())) == 1
    assert {p.name for p in directory.iterdir()} == {
        'ch000.json', 'ch001.json', 'manifest.json', 'SOURCE_NOTICE.md', *source.SOURCE_MATERIALS.values()}
    assert read_json(directory / 'manifest.json')['provenance'] == provenance
    assert provenance['acquisition_complete'] is True
    for name, digest in provenance['local_chapter_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    for name, digest in provenance['local_notice_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    assert '重新序列化' in (directory / 'SOURCE_NOTICE.md').read_text(encoding='utf-8')
    assert 'DO_NOT_IMPORT_THIS_CORE' not in ''.join(p.read_text(encoding='utf-8') for p in directory.iterdir())
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize(('status', 'code'), [(302, 'SOURCE_REDIRECT_BLOCKED'),
                                                (404, 'SOURCE_DOWNLOAD_FAILED'),
                                                (500, 'SOURCE_DOWNLOAD_FAILED')])
def test_http_failures_do_not_import(tmp_path, pinned, status, code):
    _, _, response = pinned
    response.status_code = status
    with pytest.raises(ValueError, match='^' + code + '$'):
        source.acquire_detroit(GameService(tmp_path), True)
    assert not list((tmp_path / 'stories').iterdir())
    assert response.closed


def test_network_exception_is_redacted_and_retriable(tmp_path, pinned, monkeypatch):
    data, calls, _ = pinned
    def broken(*args, **kwargs):
        raise requests.ConnectionError('SECRET_PRIVATE_PROXY_AND_TOKEN')
    monkeypatch.setattr(source.requests, 'get', broken)
    with pytest.raises(ValueError, match='^SOURCE_DOWNLOAD_FAILED$') as error:
        source.acquire_detroit(GameService(tmp_path), True)
    assert 'SECRET_PRIVATE' not in str(error.value)
    monkeypatch.setattr(source.requests, 'get', lambda *args, **kwargs: Response(data))
    assert source.acquire_detroit(GameService(tmp_path), True)['id']


def test_wrong_hash_rejected_before_store_mutation(tmp_path, pinned):
    _, _, response = pinned
    response.content += b'changed archive'
    with pytest.raises(ValueError, match='^SOURCE_HASH_MISMATCH$'):
        source.acquire_detroit(GameService(tmp_path), True)
    assert not list((tmp_path / 'stories').iterdir())


@pytest.mark.parametrize('declared_size', [False, True])
def test_download_is_bounded_even_without_content_length(tmp_path, pinned, monkeypatch, declared_size):
    data, _, response = pinned
    monkeypatch.setattr(source, 'MAX_DOWNLOAD_BYTES', len(data) - 1)
    if declared_size:
        response.headers = {'Content-Length': str(len(data))}
    with pytest.raises(ValueError, match='^SOURCE_DOWNLOAD_TOO_LARGE$'):
        source.acquire_detroit(GameService(tmp_path), True)
    assert not list((tmp_path / 'stories').iterdir())


def test_elapsed_limit_closes_response(tmp_path, pinned, monkeypatch):
    _, _, response = pinned
    times = iter([0, source.MAX_DOWNLOAD_SECONDS + 1])
    monkeypatch.setattr(source.time, 'monotonic', lambda: next(times))
    with pytest.raises(ValueError, match='^SOURCE_DOWNLOAD_TIMEOUT$'):
        source.acquire_detroit(GameService(tmp_path), True)
    assert response.closed
    assert not list((tmp_path / 'stories').iterdir())


def test_correct_hash_but_wrong_chapter_count_is_not_imported(tmp_path, pinned, monkeypatch):
    monkeypatch.setattr(source, 'SOURCE_CHAPTER_COUNT', 3)
    with pytest.raises(ValueError, match='^SOURCE_CONTENT_INVALID$'):
        source.acquire_detroit(GameService(tmp_path), True)
    assert not list((tmp_path / 'stories').iterdir())


def test_incomplete_existing_story_is_preserved(tmp_path, pinned):
    _, calls, _ = pinned
    service = GameService(tmp_path)
    story = source.acquire_detroit(service, True)
    (tmp_path / 'stories' / story['id'] / 'ch001.json').unlink()
    with pytest.raises(ValueError, match='^SOURCE_LOCAL_COPY_INCOMPLETE$'):
        source.acquire_detroit(service, True)
    assert len(calls) == 1
    assert len(list((tmp_path / 'stories').iterdir())) == 1


@pytest.mark.parametrize('name', ['ch000.json', 'UPSTREAM_LICENSE_SCOPE.md', 'SOURCE_NOTICE.md'])
def test_changed_local_copy_is_never_silently_replaced(tmp_path, pinned, name):
    _, calls, _ = pinned
    service = GameService(tmp_path)
    story = source.acquire_detroit(service, True)
    changed = tmp_path / 'stories' / story['id'] / name
    changed.write_text('A private local edit to retain', encoding='utf-8')
    with pytest.raises(ValueError, match='^SOURCE_LOCAL_COPY_CHANGED$'):
        source.acquire_detroit(service, True)
    assert changed.read_text(encoding='utf-8') == 'A private local edit to retain'
    assert len(calls) == 1
    assert len(list((tmp_path / 'stories').iterdir())) == 1


def test_import_write_failure_does_not_publish_half_complete_story(tmp_path, pinned, monkeypatch):
    actual_write = source.write_json
    def broken(*args, **kwargs):
        raise OSError('SECRET_PRIVATE_STORAGE_PATH')
    monkeypatch.setattr(source, 'write_json', broken)
    service = GameService(tmp_path)
    with pytest.raises(ValueError, match='^SOURCE_STORAGE_FAILED$') as error:
        source.acquire_detroit(service, True)
    assert 'SECRET_PRIVATE' not in str(error.value)
    assert list((tmp_path / 'stories').iterdir()) == []
    assert not list(tmp_path.glob('.source-import-*'))
    monkeypatch.setattr(source, 'write_json', actual_write)
    story = source.acquire_detroit(service, True)
    assert story['provenance']['acquisition_complete'] is True
    assert len(list((tmp_path / 'stories').iterdir())) == 1


def test_concurrent_process_lock_prevents_network(tmp_path, pinned):
    _, calls, _ = pinned
    service = GameService(tmp_path)
    with source._acquisition_lock(service.directory):
        with pytest.raises(ValueError, match='^SOURCE_BUSY$'):
            source.acquire_detroit(service, True)
    assert calls == []
    assert source.acquire_detroit(service, True)['id']


def test_verified_local_zip_keeps_notices_reuses_without_network_and_checks_new_game_integrity(tmp_path, pinned):
    from fish_story.import_pack import import_story_pack
    data, calls, _ = pinned
    service = GameService(tmp_path)
    imported = import_story_pack(service, data)
    assert service.default_story_id() == imported['id']
    directory = service.directory / 'stories' / imported['id']
    assert all((directory / name).is_file() for name in source.SOURCE_MATERIALS.values())
    assert (directory / 'SOURCE_NOTICE.md').is_file()
    reused = source.acquire_detroit(service, True)
    assert reused['id'] == imported['id'] and calls == []
    assert reused['provenance']['source_terms_accepted_at'] is None
    service.start('first-player')
    chapter = directory / 'ch000.json'
    chapter.write_bytes(chapter.read_bytes() + b' ')
    with pytest.raises(ValueError, match='SOURCE_LOCAL_COPY_CHANGED'):
        service.start('second-player')
    assert len(service.sessions()) == 1


def test_verified_archive_english_import_is_not_mislabeled_as_chinese_detroit(tmp_path, monkeypatch):
    from fish_story.import_pack import import_story_pack
    raw = io.BytesIO(archive_bytes())
    with zipfile.ZipFile(raw, 'a', zipfile.ZIP_DEFLATED) as archive:
        chapter = json.loads(archive.read('original-source/01_json/zh/ch01.json'))
        archive.writestr('original-source/01_json/en/ch01.json', json.dumps(chapter))
    data = raw.getvalue()
    monkeypatch.setattr(source, 'SOURCE_SHA256', hashlib.sha256(data).hexdigest())
    service = GameService(tmp_path)
    result = import_story_pack(service, data, title='English user pack', language='en')
    assert result['title'] == 'English user pack'
    assert service.default_story_id() is None
    assert not next(story for story in service.stories() if story['id'] == result['id'])['is_detroit']
