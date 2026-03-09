"""测试 s3_source 模块的 URI 解析功能"""

from fyuneru.s3_source import parse_blob_uri


def test_parse_blob_uri_normal():
    bucket_id, key = parse_blob_uri("blob://my-images/photos/2024/img001.jpg")
    assert bucket_id == "my-images", f"期望 'my-images'，得到 '{bucket_id}'"
    assert key == "photos/2024/img001.jpg", f"期望 'photos/2024/img001.jpg'，得到 '{key}'"


def test_parse_blob_uri_simple_key():
    bucket_id, key = parse_blob_uri("blob://backup/file.bin")
    assert bucket_id == "backup"
    assert key == "file.bin"


def test_parse_blob_uri_wrong_scheme():
    try:
        parse_blob_uri("s3://bucket/key")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不支持的协议" in str(e)


def test_parse_blob_uri_empty_bucket():
    try:
        parse_blob_uri("blob:///key")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


def test_parse_blob_uri_empty_key():
    try:
        parse_blob_uri("blob://bucket/")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


def test_parse_blob_uri_no_key():
    try:
        parse_blob_uri("blob://bucket")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


if __name__ == "__main__":
    test_parse_blob_uri_normal()
    test_parse_blob_uri_simple_key()
    test_parse_blob_uri_wrong_scheme()
    test_parse_blob_uri_empty_bucket()
    test_parse_blob_uri_empty_key()
    test_parse_blob_uri_no_key()
    print("所有 parse_blob_uri 测试通过")
