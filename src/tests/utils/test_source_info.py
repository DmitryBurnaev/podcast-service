import pytest

from common.enums import SourceType
from common.exceptions import InvalidRequestError
from modules.providers.utils import extract_source_info


@pytest.mark.parametrize(
    "source_url,source_type,source_id",
    [
        ("https://music.yandex.ru/album/1/track/2/", SourceType.YANDEX, "2"),
        ("https://www.youtube.com/watch?v=FooBar_1234", SourceType.YOUTUBE, "FooBar_1234"),
        ("https://youtu.be/FooBar12345", SourceType.YOUTUBE, "FooBar12345"),
    ],
)
def test_fetch_source_type__ok(source_url: str, source_type: SourceType, source_id: str):
    source_info = extract_source_info(source_url)
    assert source_info.type == source_type
    assert source_info.url == source_url
    assert source_info.id == source_id
    assert source_info.cookie is None


@pytest.mark.parametrize(
    "source_url",
    [
        "https://www.fake.com/2132/",
        "https://youtu.be/12",
    ],
)
def test_fetch_source_type__didnt_match(source_url: str):
    with pytest.raises(InvalidRequestError) as e:
        extract_source_info(source_url)

    assert e.value.details == f"Requested domain is not supported now {source_url}"
