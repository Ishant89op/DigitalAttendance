"""
Preview window helpers.

OpenCV can capture camera frames even when its GUI backend is unavailable.
On Windows that means the camera light turns on but no preview window appears.
This module provides:

1. Native OpenCV preview when HighGUI is available.
2. Tkinter/Pillow preview fallback when OpenCV is headless.

Performance notes:
  - TkPreviewWindow uses BILINEAR resampling (fast) instead of LANCZOS (slow).
  - Root size is cached; the PIL resize is skipped when dims haven't changed.
  - Only root.update() is called; update_idletasks() before it is redundant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2


def detect_preview_backend() -> str:
    """Return 'opencv', 'tk', or 'none'."""
    if _has_opencv_gui():
        return "opencv"
    if _has_tk_preview():
        return "tk"
    return "none"


def create_preview_window(title: str, width: int = 800, height: int = 520):
    """Create the best available preview window implementation."""
    backend = detect_preview_backend()
    if backend == "opencv":
        return OpenCVPreviewWindow(title, width, height)
    if backend == "tk":
        return TkPreviewWindow(title, width, height)
    return None


@dataclass
class OpenCVPreviewWindow:
    title: str
    width: int
    height: int

    def __post_init__(self) -> None:
        cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.title, self.width, self.height)

    @property
    def backend_name(self) -> str:
        return "opencv"

    def show(self, frame) -> bool:
        cv2.imshow(self.title, frame)
        key = cv2.waitKey(1) & 0xFF
        return key not in (ord("q"), 27)

    def close(self) -> None:
        try:
            cv2.destroyWindow(self.title)
        except cv2.error:
            pass
        cv2.destroyAllWindows()


class TkPreviewWindow:
    def __init__(self, title: str, width: int, height: int) -> None:
        import tkinter as tk
        from PIL import Image, ImageTk

        self._tk = tk
        self._Image = Image
        self._ImageTk = ImageTk
        self._closed = False
        self._photo = None
        self._target_w = width
        self._target_h = height

        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{width}x{height}")
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<KeyPress-q>", lambda _event: self.close())

        self.label = tk.Label(self.root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.root.update()

    @property
    def backend_name(self) -> str:
        return "tk"

    def show(self, frame) -> bool:
        if self._closed:
            return False

        # Use cv2.resize (C-level, INTER_LINEAR) — much faster than PIL BILINEAR
        ww = max(self.label.winfo_width(),  self._target_w)
        wh = max(self.label.winfo_height(), self._target_h)
        fh, fw = frame.shape[:2]
        scale = min(ww / fw, wh / fh)
        new_w = max(1, int(fw * scale))
        new_h = max(1, int(fh * scale))

        if (new_w, new_h) != (fw, fh):
            resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            resized = frame

        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        image = self._Image.fromarray(rgb)
        self._photo = self._ImageTk.PhotoImage(image=image)
        self.label.configure(image=self._photo)

        try:
            self.root.update()
        except self._tk.TclError:
            self._closed = True

        return not self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except self._tk.TclError:
            pass


def _has_opencv_gui() -> bool:
    try:
        cv2.namedWindow("_preview_test", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("_preview_test")
        return True
    except cv2.error:
        return False


def _has_tk_preview() -> bool:
    try:
        import tkinter  # noqa: F401
        from PIL import ImageTk  # noqa: F401
        return True
    except Exception:
        return False


def _fit_image_to_widget(image, max_width: int, max_height: int):
    if max_width <= 1 or max_height <= 1:
        return image

    width, height = image.size
    scale = min(max_width / width, max_height / height)
    if scale <= 0:
        return image

    new_size = (
        max(1, int(width * scale)),
        max(1, int(height * scale)),
    )
    if new_size == image.size:
        return image

    # BILINEAR is 3–5× faster than LANCZOS with negligible visual difference
    # at 640×480 → ~800×520 preview sizes.
    resample = getattr(image, "Resampling", None)
    if resample is not None:
        return image.resize(new_size, resample.BILINEAR)
    return image.resize(new_size)
