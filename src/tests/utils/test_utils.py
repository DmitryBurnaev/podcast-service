import tempfile
from pathlib import Path

from modules.podcast.utils import move_file, get_file_size, delete_file


def test_move_file__ok():
    source_content = "test content"
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as source_file:
        source_file.write(source_content)
        source_path = Path(source_file.name)

    dest_path = Path(tempfile.gettempdir()) / "moved_file.txt"

    move_file(source_path, dest_path)

    assert not source_path.exists()
    assert dest_path.exists()
    assert dest_path.read_text() == source_content

    dest_path.unlink()


def test_move_file__nonexistent_file__skip():
    nonexistent_path = Path(tempfile.gettempdir()) / "nonexistent.txt"
    dest_path = Path(tempfile.gettempdir()) / "dest.txt"
    move_file(nonexistent_path, dest_path)
    assert not dest_path.exists()
    if dest_path.exists():
        dest_path.unlink()


def test_move_file__replace_exists__ok():
    source_content = "test content"
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as source_file:
        source_file.write(source_content)
        source_path = Path(source_file.name)

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as dest_file:
        dest_file.write("another content")
        dest_path = Path(dest_file.name)

    move_file(source_path, dest_path)
    assert dest_path.exists()
    assert not source_path.exists()

    assert dest_path.read_text() == source_content
    dest_path.unlink()


def test_returns_correct_size_for_regular_file():
    test_file = Path("test.txt")
    test_content = b"test content"
    test_file.write_bytes(test_content)

    try:
        result = get_file_size(test_file)
        assert result == len(test_content)
    finally:
        test_file.unlink()


def test_delete_existing_file__ok():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as source_file:
        source_file.write("test content")
        source_path = Path(source_file.name)

    delete_file(source_path)

    assert not source_path.exists()
