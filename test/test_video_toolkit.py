"""测试 video_toolkit 的规格校验与真实降采样行为。

降采样用 PyAV 现场合成一段源视频，不依赖外部素材。
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import av
import numpy as np
from av.video.frame import VideoFrame

from fyuneru.result import is_failure, is_success, unwrap
from fyuneru.video_toolkit import (
    MediaProfile,
    VideoProcessError,
    downsample_video,
    probe_video,
    safe_downsample_video,
    scaled_size,
)


def _synth_video(
    path: Path,
    width: int = 320,
    height: int = 240,
    fps: int = 10,
    seconds: int = 3,
) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = width  # type: ignore[union-attr]
        stream.height = height  # type: ignore[union-attr]
        stream.pix_fmt = "yuv420p"  # type: ignore[union-attr]
        for index in range(fps * seconds):
            array = np.full(
                (height, width, 3), index * 3 % 256, dtype=np.uint8
            )
            frame = VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):  # type: ignore[union-attr]
                container.mux(packet)
        for packet in stream.encode(None):  # type: ignore[union-attr]
            container.mux(packet)


def test_profile_validation() -> None:
    for kwargs in (
        {"target_height": 1},
        {"target_fps": 0},
        {"crf": 99},
        {"version": " "},
    ):
        try:
            MediaProfile(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"期望 ValueError: {kwargs}")


def test_profile_descriptor_encodes_spec() -> None:
    profile = MediaProfile(target_height=480, target_fps=1, version="v2")
    assert profile.descriptor() == "v2-480p-1fps"


def test_scaled_size_keeps_aspect_and_parity() -> None:
    assert scaled_size(1920, 1080, 480) == (852, 480)
    assert scaled_size(640, 360, 480) == (640, 360), "低于目标高度不得上采样"
    assert scaled_size(641, 361, 480) == (640, 360), "宽高必须为偶数"

    for args in ((0, 100, 480), (100, -1, 480), ("a", 100, 480)):
        try:
            scaled_size(*args)
        except VideoProcessError:
            continue
        raise AssertionError(f"期望 VideoProcessError: {args}")


def test_probe_reads_source_geometry() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.mp4"
        _synth_video(source, width=320, height=240, fps=10, seconds=2)
        stat = probe_video(source)
    assert (stat.width, stat.height) == (320, 240)
    assert stat.duration_seconds is not None and stat.duration_seconds > 1.0


def test_downsample_reduces_fps_and_height() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.mp4"
        destination = Path(tmp) / "out" / "derived.mp4"
        _synth_video(source, width=640, height=480, fps=10, seconds=3)

        report = downsample_video(
            source,
            destination,
            profile=MediaProfile(target_height=240, target_fps=1),
            threads=1,
        )

        assert destination.exists(), "派生文件必须落盘"
        assert report.size_bytes > 0
        assert (report.width, report.height) == (320, 240)
        assert 2 <= report.frames_written <= 4, (
            f"3s @1fps 期望约 3 帧，实际 {report.frames_written}"
        )

        derived = probe_video(destination)
        assert (derived.width, derived.height) == (320, 240)


def test_downsample_drops_audio_and_extra_streams() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.mp4"
        destination = Path(tmp) / "derived.mp4"
        _synth_video(source, width=320, height=240, fps=10, seconds=2)
        downsample_video(
            source,
            destination,
            profile=MediaProfile(target_height=240, target_fps=1),
            threads=1,
        )
        with av.open(str(destination)) as container:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 0, "音频轨必须被丢弃"
            assert len(container.streams) == 1, "只允许保留一条视频流"


def test_output_size_budget_enforced() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.mp4"
        destination = Path(tmp) / "derived.mp4"
        _synth_video(source, width=320, height=240, fps=10, seconds=2)
        try:
            downsample_video(
                source,
                destination,
                profile=MediaProfile(target_height=240, target_fps=1),
                threads=1,
                max_output_bytes=1,
            )
        except VideoProcessError:
            return
    raise AssertionError("超出体积预算必须抛 VideoProcessError")


def test_safe_wrapper_returns_result() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.mp4"
        _synth_video(source, width=320, height=240, fps=10, seconds=2)
        ok = safe_downsample_video(
            source,
            Path(tmp) / "derived.mp4",
            profile=MediaProfile(target_height=240, target_fps=1),
            threads=1,
        )
        assert is_success(ok)
        assert unwrap(ok).frames_written > 0

        bad = safe_downsample_video(
            Path(tmp) / "missing.mp4",
            Path(tmp) / "derived2.mp4",
            threads=1,
        )
        assert is_failure(bad), "不存在的源必须返回 Failure"


def main() -> None:
    test_profile_validation()
    test_profile_descriptor_encodes_spec()
    test_scaled_size_keeps_aspect_and_parity()
    test_probe_reads_source_geometry()
    test_downsample_reduces_fps_and_height()
    test_downsample_drops_audio_and_extra_streams()
    test_output_size_budget_enforced()
    test_safe_wrapper_returns_result()
    print("test_video_toolkit: 全部通过")


if __name__ == "__main__":
    main()
