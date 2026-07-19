from __future__ import annotations

from pathlib import Path

import numpy as np


def extract_keyframes(path: Path, max_frames: int = 15) -> list[np.ndarray]:
    """Sample representative frames from a video via scene-cut detection.

    Sampling only at scene changes (instead of every frame, or a fixed fps)
    keeps a large video library tractable: a two-minute clip yields a
    handful of frames instead of thousands, while still covering every
    distinct person/place that appears in it.
    """
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video)
    scenes = scene_manager.get_scene_list()

    if not scenes:
        return [_grab_frame(video, video.duration.get_frames() // 2)]

    frames = []
    for start, _end in scenes[:max_frames]:
        frames.append(_grab_frame(video, start.get_frames()))
    return frames


def _grab_frame(video, frame_num: int) -> np.ndarray:
    video.seek(frame_num)
    frame = video.read()
    return frame
