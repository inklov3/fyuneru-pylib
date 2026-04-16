from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger

from fyuneru.logger import configure_logger
from fyuneru.result import unwrap


def test_configure_logger():
    with TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        unwrap(configure_logger(log_dir=log_dir))
        logger.info("Hello, world!")
        assert (log_dir / "latest.log").exists()


if __name__ == "__main__":
    test_configure_logger()
    print("logger 测试通过")
