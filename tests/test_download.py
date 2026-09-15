import io
import json
import tarfile

import pytest

from mascope.download import unpack


def archive(path, name, content=b"{}", symlink=False):
    with tarfile.open(path, "w:gz") as bundle:
        member = tarfile.TarInfo(name)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = "/tmp"
        else:
            member.size = len(content)
        bundle.addfile(member, None if symlink else io.BytesIO(content))


@pytest.mark.parametrize(
    "name,symlink",
    [
        ("runtime/../../escape", False),
        ("/absolute/file", False),
        ("runtime/link", True),
        ("other/file", False),
    ],
)
def test_unsafe_archives_rejected(tmp_path, name, symlink):
    path = tmp_path / "bundle.tar.gz"
    archive(path, name, symlink=symlink)
    with pytest.raises(ValueError):
        unpack(path, tmp_path / "result", "runtime")
    assert not (tmp_path / "result").exists()


def test_unpack_and_no_overwrite(tmp_path):
    path = tmp_path / "bundle.tar.gz"
    archive(path, "runtime/manifest.json", b'{"schema_version":"1.0"}')
    destination = tmp_path / "result"
    unpack(path, destination, "runtime")
    assert (
        json.loads((destination / "manifest.json").read_text())["schema_version"]
        == "1.0"
    )
    with pytest.raises(FileExistsError):
        unpack(path, destination, "runtime")


def test_download_checks_digest_before_install(tmp_path, monkeypatch):
    import hashlib
    from mascope.download import download

    source = tmp_path / "source"
    source.mkdir()
    path = source / "runtime.tar.gz"
    archive(path, "runtime/manifest.json")
    item = {
        "filename": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }
    monkeypatch.setattr(
        "mascope.download.release_manifest", lambda: {"components": {"runtime": item}}
    )
    download(source.as_uri(), tmp_path / "good")
    assert (tmp_path / "good/runtime/manifest.json").is_file()
    item["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        download(source.as_uri(), tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
