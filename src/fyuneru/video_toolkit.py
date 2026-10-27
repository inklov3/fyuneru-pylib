"""视频降采样：把任意源视频转成"只有一条低分辨率低帧率视频流"的 MP4。

面向模型消费场景：上游多模态模型按帧和分辨率计费/限额，源素材（例如无人机
4K 高帧率 MP4）往往比模型实际需要的信息量高一两个数量级。本模块只做一件事，
把源视频规约到目标规格，同时丢掉音频、DJI 预览用的 mjpeg 轨和 data 轨。

设计取舍：
- 输出规格由 `MediaProfile` 显式携带并可版本化，不写死在代码里——换规格等于
  换派生产物，需要能在产物路径上区分开；
- 只保留第一条视频流。多视频流容器里其余轨道都是预览/缩略图，对模型无用；
- 转码走 PyAV 内存管道，不外挂 ffmpeg 进程，便于在 worker 内统计与限流；
- 帧抽取靠"固定输出 timebase + 自算 pts"，而不是指望编码器自己降帧率。
"""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from loguru import logger

from fyuneru.result import ResultE, safe

DEFAULT_ENCODER = "libx264"
DEFAULT_PIXEL_FORMAT = "yuv420p"

# 关键帧探测最多扫这么多 packet 头。超出即认为文件异常长，不再据不完整证据
# 决定快路径。只读 packet 头，不解码，所以代价是一次索引扫描。
KEYFRAME_PROBE_PACKETS = 200_000

# 关键帧间隔在"目标帧间隔 × 该系数"以内才允许走 skip_frame=NONKEY 快路径。
# 超出说明按关键帧抽帧会在某些区间连续丢帧，必须退回完整解码。
KEYFRAME_GOP_TOLERANCE = 1.5


class VideoProcessError(RuntimeError):
    """源视频无法按目标规格产出派生视频。

    这类失败几乎都是源文件固有属性（无视频流、无法解码、无可解码帧），
    重试不会改变结果，调用方应当作永久失败处理。
    """


@dataclass(frozen=True)
class MediaProfile:
    """派生视频的目标规格。

    `version` 参与派生产物的存储路径，规格变更时旧产物不会被静默复用。
    """

    target_height: int = 480
    target_fps: int = 1
    crf: int = 28
    preset: str = "veryfast"
    encoder: str = DEFAULT_ENCODER
    version: str = "v1"

    def __post_init__(self) -> None:
        if self.target_height < 2:
            raise ValueError("target_height 必须不小于 2")
        if self.target_fps < 1:
            raise ValueError("target_fps 必须不小于 1")
        if not 0 <= self.crf <= 51:
            raise ValueError("crf 必须在 [0, 51] 区间")
        if not self.version.strip():
            raise ValueError("version 不能为空")

    def descriptor(self) -> str:
        """人类可读的规格标识，可直接拼进对象存储 key。"""
        return f"{self.version}-{self.target_height}p-{self.target_fps}fps"


@dataclass(frozen=True)
class VideoStat:
    """源视频的基本参数。"""

    width: int
    height: int
    duration_seconds: float | None
    nb_frames: int | None
    codec_name: str | None


@dataclass(frozen=True)
class DownsampleReport:
    """一次降采样的结果，供调用方记账与校验。"""

    destination: Path
    size_bytes: int
    frames_written: int
    width: int
    height: int
    keyframe_only: bool
    profile: MediaProfile


def probe_video(source: str | Path) -> VideoStat:
    """读取源视频的分辨率、时长等参数，只开容器不解码。"""
    import av
    from av.container import InputContainer

    opened = av.open(str(source), mode="r")
    if not isinstance(opened, InputContainer):
        raise VideoProcessError("源对象无法以输入方式打开")
    with opened as container:
        if not container.streams.video:
            raise VideoProcessError("源对象没有可解析的视频流")
        stream = container.streams.video[0]
        codec_context = stream.codec_context
        width = codec_context.width
        height = codec_context.height
        if not isinstance(width, int) or not isinstance(height, int):
            raise VideoProcessError("源视频缺少分辨率信息")
        duration = (
            float(container.duration / 1_000_000)
            if container.duration is not None
            else None
        )
        return VideoStat(
            width=width,
            height=height,
            duration_seconds=duration,
            nb_frames=stream.frames or None,
            codec_name=getattr(codec_context, "name", None),
        )


def downsample_video(
    source: str | Path,
    destination: Path,
    profile: MediaProfile | None = None,
    threads: int = 0,
    allow_keyframe_only: bool = True,
    max_output_bytes: int | None = None,
) -> DownsampleReport:
    """把 `source` 降采样为符合 `profile` 的 MP4，写入 `destination`。

    `allow_keyframe_only` 打开时会先探测源的关键帧间隔：足够密的源可以让解码器
    在重建前就丢掉非关键帧（`skip_frame=NONKEY`），这是主要的 CPU 节省来源；
    间隔过粗时自动退回完整解码，保证抽帧结果仍然均匀。

    `threads=0` 交给 FFmpeg 自行决定；在多 worker 并发场景应显式给小值，
    否则每个 worker 都会尝试吃满整机。
    """
    import av
    from av.codec.context import ThreadType
    from av.container import InputContainer
    from av.error import FFmpegError

    active = profile if profile is not None else MediaProfile()
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        opened = av.open(str(source), mode="r")
        if not isinstance(opened, InputContainer):
            raise VideoProcessError("源对象无法以输入方式打开")
        with opened as container:
            if not container.streams.video:
                raise VideoProcessError("源对象没有可解析的视频流")
            video_in = container.streams.video[0]
            video_in.codec_context.thread_count = threads
            video_in.codec_context.thread_type = ThreadType.AUTO

            keyframe_only = False
            if allow_keyframe_only:
                keyframe_only = _decide_keyframe_only(
                    container, video_in, active.target_fps
                )
                if keyframe_only:
                    video_in.codec_context.skip_frame = "NONKEY"

            width, height = scaled_size(
                video_in.codec_context.width,
                video_in.codec_context.height,
                active.target_height,
            )
            frames = _transcode(
                container=container,
                video_in=video_in,
                destination=destination,
                profile=active,
                width=width,
                height=height,
                threads=threads,
            )
    except VideoProcessError:
        raise
    except FFmpegError as error:
        raise VideoProcessError(f"源对象无法解码: {error}") from error

    size = destination.stat().st_size
    if size <= 0:
        raise VideoProcessError("降采样结果为空")
    if max_output_bytes is not None and size > max_output_bytes:
        raise VideoProcessError(
            f"降采样结果过大: {size} 字节 > {max_output_bytes} 字节"
        )
    return DownsampleReport(
        destination=destination,
        size_bytes=size,
        frames_written=frames,
        width=width,
        height=height,
        keyframe_only=keyframe_only,
        profile=active,
    )


@safe
def safe_downsample_video(
    source: str | Path,
    destination: Path,
    profile: MediaProfile | None = None,
    threads: int = 0,
    allow_keyframe_only: bool = True,
    max_output_bytes: int | None = None,
) -> DownsampleReport:
    """`downsample_video` 的 `ResultE` 包装。"""
    return downsample_video(
        source=source,
        destination=destination,
        profile=profile,
        threads=threads,
        allow_keyframe_only=allow_keyframe_only,
        max_output_bytes=max_output_bytes,
    )


def scaled_size(width: Any, height: Any, target_height: int) -> tuple[int, int]:
    """按目标高度等比缩放，并保证宽高为偶数。

    已经低于目标高度的源保持原样而不上采样：放大只增加字节数，不增加信息。
    """
    if not isinstance(width, int) or not isinstance(height, int):
        raise VideoProcessError("源视频缺少分辨率信息")
    if width <= 0 or height <= 0:
        raise VideoProcessError(f"源视频分辨率无效: {width}x{height}")
    if height <= target_height:
        return _even(width), _even(height)
    return _even(round(width * target_height / height)), _even(target_height)


def _even(value: int) -> int:
    """向下取偶；yuv420p 要求宽高均为偶数。"""
    return max(2, value - (value % 2))


def _transcode(
    container: Any,
    video_in: Any,
    destination: Path,
    profile: MediaProfile,
    width: int,
    height: int,
    threads: int,
) -> int:
    import av
    from av.codec.context import ThreadType
    from av.video.stream import VideoStream

    with av.open(
        str(destination),
        mode="w",
        format="mp4",
        options={"movflags": "faststart"},
    ) as output:
        added = output.add_stream(profile.encoder, rate=profile.target_fps)
        if not isinstance(added, VideoStream):
            raise VideoProcessError(f"编码器未产出视频流: {profile.encoder}")
        stream = added
        stream.width = width
        stream.height = height
        stream.pix_fmt = DEFAULT_PIXEL_FORMAT
        stream.codec_context.thread_count = threads
        stream.codec_context.thread_type = ThreadType.AUTO
        stream.options = {
            "crf": str(profile.crf),
            "preset": profile.preset,
        }
        # 固定输出 timebase 并自行计算 pts，这才是真正降帧率的地方：
        # 若把每个解码帧都编码进去，输出仍是源帧率。
        #
        # timebase 存成局部变量而不是每轮从 stream 读回：一旦开始 mux，
        # stream.time_base 会变成容器重标定后的值，用它盖帧会被 muxer 拒绝。
        time_base = Fraction(1, profile.target_fps)
        stream.time_base = time_base
        step = 1.0 / profile.target_fps
        next_at = 0.0
        index = 0
        for frame in container.decode(video_in):
            elapsed = _frame_seconds(frame)
            if elapsed is not None:
                if elapsed + 1e-9 < next_at:
                    continue
                next_at = elapsed + step
            scaled = frame.reformat(
                width=width,
                height=height,
                format=DEFAULT_PIXEL_FORMAT,
            )
            scaled.pts = index
            scaled.time_base = time_base
            index += 1
            for packet in stream.encode(scaled):
                output.mux(packet)
        if index == 0:
            raise VideoProcessError("源对象没有可解码的视频帧")
        for packet in stream.encode(None):
            output.mux(packet)
    return index


def _frame_seconds(frame: Any) -> float | None:
    elapsed = getattr(frame, "time", None)
    if isinstance(elapsed, (int, float)):
        return float(elapsed)
    pts = getattr(frame, "pts", None)
    time_base = getattr(frame, "time_base", None)
    if pts is None or not time_base:
        return None
    return float(pts * time_base)


def _decide_keyframe_only(container: Any, stream: Any, target_fps: int) -> bool:
    gop = keyframe_interval(container, stream, KEYFRAME_PROBE_PACKETS)
    budget = KEYFRAME_GOP_TOLERANCE / target_fps
    decided = gop is not None and gop <= budget
    logger.info(
        "video.gop max_interval_s={} budget_s={:.2f} keyframe_only={}",
        f"{gop:.3f}" if gop is not None else "unknown",
        budget,
        decided,
    )
    return decided


def keyframe_interval(
    container: Any, stream: Any, probe_packets: int = KEYFRAME_PROBE_PACKETS
) -> float | None:
    """返回源视频最大的关键帧间隔（秒），无法判定时返回 None。

    取*最大*而非中位间隔：关键帧通常 1s 一个、偶尔 5s 一个的源能通过中位数
    检验，然后在那段稀疏区间里连续丢帧。最大间隔才是唯一约束最坏情况的量。

    只 demux packet 头，不解码。探测会消耗 packet，所以结束后必须回卷；
    回卷失败时返回 None，而不是把调用方留在文件中段。
    """
    time_base = getattr(stream, "time_base", None)
    if not time_base:
        return None
    stamps: list[float] = []
    seen = 0
    truncated = False
    try:
        for packet in container.demux(stream):
            if packet.pts is None:
                continue
            seen += 1
            if packet.is_keyframe:
                stamps.append(float(packet.pts * time_base))
            if seen >= probe_packets:
                truncated = True
                break
    except Exception:  # noqa: BLE001 - 探测仅作参考，失败即放弃快路径
        _rewind(container)
        return None
    if not _rewind(container):
        return None
    if truncated or len(stamps) < 3:
        return None
    stamps.sort()
    gaps = [
        later - earlier
        for earlier, later in zip(stamps, stamps[1:], strict=False)
        if later > earlier
    ]
    if not gaps:
        return None
    return max(gaps)


def _rewind(container: Any) -> bool:
    try:
        container.seek(0)
    except Exception:  # noqa: BLE001 - 回卷失败只意味着放弃快路径
        return False
    return True
