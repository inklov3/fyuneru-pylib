from urllib.parse import urlparse

from returns.result import safe


def unify_urlparser(url: str): ...


def unify_urlreader(url: str) -> bytes: ...
