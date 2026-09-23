# fyuneru.video_toolkit

视频降采样：把任意源视频转成"只有一条低分辨率低帧率视频流"的 MP4。

## 设计目标

面向模型消费场景：上游多模态模型按帧和分辨率计费/限额，源素材（例如无人机 4K 高帧率 MP4）往往比模型实际需要的信息量高一两个数量级。本模块只做一件事，把源视频规约到目标规格，同时丢掉音频、DJI 预览用的 mjpeg 轨和 data 轨。

## 核心 API

```python
from pathlib import Path
from fyuneru.video_toolkit import (
    MediaProfile,
    downsample_video,
    probe_video,
    safe_downsample_video,
)

profile = MediaProfile(
    target_height=480,
    target_fps=1,
    crf=28,
    preset="veryfast",
    version="v1",
)

report = downsample_video(
    source=Path("source.mp4"),
    destination=Path("derived/480p-1fps.mp4"),
    profile=profile,
    threads=2,
    allow_keyframe_only=True,
    max_output_bytes=100 * 1024 * 1024,
)

print(f"输出: {report.size_bytes} 字节, {report.frames_written} 帧")
```

## MediaProfile

```python
@dataclass(frozen=True)
class MediaProfile:
    target_height: int = 480
    target_fps: int = 1
    crf: int = 28
    preset: str = "veryfast"
    encoder: str = "libx264"
    version: str = "v1"

    def descriptor(self) -> str:
        """返回 'v1-480p-1fps' 格式的规格标识。"""
```

`version` 参与派生产物的存储路径，规格变更时旧产物不会被静默复用。

## downsample_video

```python
def downsample_video(
    source: str | Path,
    destination: Path,
    profile: MediaProfile | None = None,
    threads: int = 0,
    allow_keyframe_only: bool = True,
    max_output_bytes: int | None = None,
) -> DownsampleReport:
```

- `threads=0`：交给 FFmpeg 自行决定；多 worker 并发时应显式给小值；
- `allow_keyframe_only`：探测源关键帧间隔，足够密时走 `skip_frame=NONKEY` 快路径；
- `max_output_bytes`：超出预算时抛 `VideoProcessError`；
- 失败类型：
  - `VideoProcessError`：源文件固有属性导致的失败（无视频流、无法解码、无可解码帧），重试无效；
  - 其余异常：I/O、权限等基础设施失败。

## probe_video

```python
def probe_video(source: str | Path) -> VideoStat:
```

只开容器不解码，读取分辨率、时长等参数。

```python
@dataclass(frozen=True)
class VideoStat:
    width: int
    height: int
    duration_seconds: float | None
    nb_frames: int | None
    codec_name: str | None
```

## DownsampleReport

```python
@dataclass(frozen=True)
class DownsampleReport:
    destination: Path
    size_bytes: int
    frames_written: int
    width: int
    height: int
    keyframe_only: bool
    profile: MediaProfile
```

供调用方记账与校验。`keyframe_only=True` 说明走了快路径。

## safe_downsample_video

```python
def safe_downsample_video(...) -> ResultE[DownsampleReport]:
```

`downsample_video` 的 `ResultE` 包装。

## 关键帧快路径

源的关键帧间隔在"目标帧间隔 × `KEYFRAME_GOP_TOLERANCE`"以内时，解码器可在重建前丢掉非关键帧（`skip_frame=NONKEY`），这是主要的 CPU 节省来源。间隔过粗时自动退回完整解码，保证抽帧结果仍然均匀。

探测只 demux packet 头，不解码，代价是一次索引扫描。

## 典型场景

### 1. 批量预处理

```python
from pathlib import Path
from fyuneru.video_toolkit import MediaProfile, downsample_video

profile = MediaProfile(target_height=480, target_fps=1, version="v2")
for source in Path("raw/").glob("*.mp4"):
    destination = Path("prepared") / profile.descriptor() / source.name
    try:
        report = downsample_video(
            source,
            destination,
            profile=profile,
            threads=2,
            max_output_bytes=50 * 1024 * 1024,
        )
        print(f"{source.name}: {report.size_bytes} 字节")
    except VideoProcessError as error:
        print(f"{source.name} 失败: {error}")
```

### 2. Ray actor 内降采样

```python
import ray
from pathlib import Path
from fyuneru.video_toolkit import MediaProfile, downsample_video

@ray.remote
class PrepActor:
    def __init__(self, threads: int = 2):
        self.profile = MediaProfile(target_height=480, target_fps=1)
        self.threads = threads

    def process(self, source: str, destination: str) -> dict:
        report = downsample_video(
            Path(source),
            Path(destination),
            profile=self.profile,
            threads=self.threads,
        )
        return {
            "size_bytes": report.size_bytes,
            "frames_written": report.frames_written,
        }
```

### 3. 与 s3_toolkit 集成

```python
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fyuneru.result import unwrap
from fyuneru.s3_toolkit import bind_s3_reader, bind_s3_writer
from fyuneru.video_toolkit import MediaProfile, downsample_video

reader = bind_s3_reader(client, "source-bucket")
writer = bind_s3_writer(client, "workspace-bucket")
profile = MediaProfile(target_height=480, target_fps=1, version="v1")

with TemporaryDirectory() as tmp:
    source_local = Path(tmp) / "source.mp4"
    derived_local = Path(tmp) / "derived.mp4"

    # 下载源
    def save(stream):
        source_local.write_bytes(stream.read())
        return None

    unwrap(reader("raw/video.mp4", save))

    # 降采样
    report = downsample_video(source_local, derived_local, profile=profile, threads=2)

    # 上传派生视频
    unwrap(writer(f"prepared/{profile.descriptor()}/video.mp4", BytesIO(derived_local.read_bytes())))
```

## 关键约束

- 只保留第一条视频流，丢弃音频和其余轨道；
- 输出规格由 `MediaProfile` 显式携带并可版本化；
- 转码走 PyAV 内存管道，不外挂 ffmpeg 进程；
- 帧抽取靠"固定输出 timebase + 自算 pts"，不依赖编码器自动降帧率；
- `VideoProcessError` 是源文件固有属性导致的失败，重试无效，应作永久失败处理。
