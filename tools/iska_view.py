"""Plays an .iska animation in a window (Python + tkinter + Pillow, nothing to build).

    python tools/iska_view.py                      # plays assets/rabbit3.iska
    python tools/iska_view.py assets/rabbit3.iska --scale 4 --anim peek
    python tools/iska_view.py --selftest 6 --out build/rabbit3/view.png   # headless
    python tools/iska_view.py --pose 1200                                 # world transforms

The frames are built from the binary by the same blitter as the C++ runtime
(`iska_common.blit_part`): what the window shows is what the engine displays, to
the pixel. No SDL, no CMake, no Blender -- this is the quickest way to look at an
asset, and it runs on any machine with Python.

Keys
    space       play / pause
    left/right  previous / next animation
    up/down     speed x2 / /2              (`0` = back to 1x)
    , .         step -/+ 10 ms             (one engine tick)
    [ ]         step -/+ 100 ms            `home` = back to t=0
    l           loop the current animation instead of playing it once
    b           cycle the background (dark / white / magenta)
    s           save the current frame as a PNG (build/iska_view/)
    click       replay the one-shot animation (like the robot's touch)
    q / esc     quit

`--selftest N` renders N frames of every animation with no window at all (useful
in a terminal or in CI) and `--pose MS` prints the resolved world transform of
every bone, which is exactly what the engine's `resolve_bones` computes.
"""
from __future__ import annotations

import argparse
import os
import time

import iska_common as iska

try:                                   # Pillow is only needed to show/save frames
    from PIL import Image, ImageTk
except Exception:                      # pragma: no cover - reported by main()
    Image = None
    ImageTk = None

ASSET_DEFAULT = os.path.join("assets", "rabbit3.iska")
STEP_MS = 10.0                         # one engine tick (see docs/FORMAT.md)
BIG_STEP_MS = 100.0
BACKDROPS = [("dark", (16, 17, 22)), ("white", (255, 255, 255)),
             ("magenta", (255, 0, 255))]
HELP_KEYS = ("space=play  <-/->=anim  up/down=speed  ,/.=step  [/]=100ms  "
             "l=loop  b=bg  s=png  click=one-shot  q=quit")

_RGB_TABLE = None


def rgb_table():
    """`65536` entries: an RGB565 value -> the 3 bytes `rgb565_to_rgb` gives.

    Built once (`rgb565_to_rgb` calls are not free) so that a frame is converted
    by one `join` instead of by one Python loop per frame. The conversion stays
    exactly the one of `iska_common`, so a saved PNG is bit-faithful.
    """
    global _RGB_TABLE
    if _RGB_TABLE is None:
        _RGB_TABLE = [bytes(iska.rgb565_to_rgb(value)) for value in range(65536)]
    return _RGB_TABLE


class Clips:
    """An asset, ready to render any frame of any of its animations."""

    def __init__(self, data: dict):
        self.data = data
        self.width, self.height = data["stage"]
        self.anims = data["anims"]
        self.names = list(data["anims"])
        self.skeleton = iska.skeleton_from_iska(data)
        self.sprites = iska.sprites_from_iska(data, self.skeleton)

    def frame(self, name: str, t_ms: float, bg: int = 0x0000):
        """RGB565 framebuffer of `name` at `t_ms` (loop taken into account)."""
        anim = self.anims[name]
        buf = iska.new_frame(self.width, self.height, bg)
        self.skeleton.draw(buf, iska.sample_pose(anim, iska.anim_time(anim, t_ms)),
                           self.sprites)
        return buf

    @staticmethod
    def painted(buf, bg: int) -> int:
        """Number of pixels differing from the background (0 = empty frame)."""
        return sum(1 for value in buf if value != bg)

    def describe(self) -> str:
        return (f"{self.width}x{self.height}, {len(self.skeleton.bones)} bones, "
                f"{len(self.skeleton.parts)} parts, {len(self.names)} animations")


class Player:
    """Timeline state: which animation, at which instant, at which speed."""

    def __init__(self, clips: Clips, name: str = "", speed: float = 1.0,
                 loop: bool = False, auto_ms: float = 0.0):
        self.clips = clips
        self.name = name or clips.names[0]
        if self.name not in clips.anims:
            raise SystemExit(f"unknown animation: {self.name} "
                             f"(available: {', '.join(clips.names)})")
        self.t = 0.0
        self.speed = speed
        self.playing = True
        self.loop = loop               # force a one-shot to loop (handy to inspect)
        self.auto_ms = auto_ms         # replay the one-shot every `auto_ms` ms
        self.auto_left = auto_ms
        self.backdrop = 0
        self.clock = time.perf_counter()

    @property
    def anim(self) -> dict:
        return self.clips.anims[self.name]

    def duration(self) -> float:
        return float(self.anim["duration"])

    def looping(self) -> bool:
        return bool(self.anim["loop"]) or self.loop

    def one_shot_names(self) -> list:
        return [name for name in self.clips.names
                if not self.clips.anims[name]["loop"]]

    def select(self, name: str) -> None:
        if name in self.clips.anims and name != self.name:
            self.name = name
            self.t = 0.0
            self.playing = True

    def shift(self, delta: int) -> None:
        index = (self.clips.names.index(self.name) + delta) % len(self.clips.names)
        self.select(self.clips.names[index])

    def trigger(self) -> None:
        """Touch (or click): replays the first one-shot animation."""
        shots = self.one_shot_names()
        if shots:
            self.name = shots[0]
        self.t = 0.0
        self.playing = True

    def advance(self, dt_ms: float) -> None:
        if not self.playing:
            return
        self.t += dt_ms
        duration = max(1.0, self.duration())
        if self.looping():
            self.t %= duration
        elif self.t >= duration:
            self.t = duration            # a one-shot holds its last pose
            self.playing = False
            self.auto_left = self.auto_ms

    def tick(self) -> None:
        """Advances by the real elapsed time (clock based: it cannot drift)."""
        now = time.perf_counter()
        dt_ms = (now - self.clock) * 1000.0
        self.clock = now
        if self.auto_ms > 0.0 and not self.playing:
            self.auto_left -= dt_ms
            if self.auto_left <= 0.0:
                self.trigger()
        self.advance(dt_ms * self.speed)

    def step(self, delta_ms: float) -> None:
        self.t = min(max(0.0, self.t + delta_ms), max(0.0, self.duration()))
        self.clock = time.perf_counter()

    def backdrop_rgb(self):
        return BACKDROPS[self.backdrop][1]

    def status(self, fps: float) -> str:
        state = "playing" if self.playing else "paused"
        kind = "loop" if self.looping() else "once"
        return (f"{self.name}  {kind}  "
                f"{self.t / 1000.0:.2f}/{self.duration() / 1000.0:.2f} s"
                f"  x{self.speed:g}  {state}  {fps:.0f} fps  "
                f"bg={BACKDROPS[self.backdrop][0]}")


# --------------------------------------------------------------------------- #
# Framebuffer -> Pillow, and the headless modes
# --------------------------------------------------------------------------- #

def to_image(buf, width: int, height: int, scale: int):
    """Pillow image of a framebuffer, `scale` times bigger (nearest neighbour)."""
    raw = b"".join([rgb_table()[value] for value in buf])
    img = Image.frombytes("RGB", (width, height), raw)
    if scale != 1:
        img = img.resize((width * scale, height * scale), Image.NEAREST)
    return img


def make_photo(img):
    """Tk image of a Pillow image (Tk 8.6 reads PNG if ImageTk is missing)."""
    import tempfile
    import tkinter as tk
    if ImageTk is not None:
        return ImageTk.PhotoImage(img)
    path = os.path.join(tempfile.gettempdir(), "iska_view_frame.png")
    img.save(path)
    return tk.PhotoImage(file=path)


def save_png(clips: Clips, player: Player, args, t_ms=None) -> str:
    """Writes the current frame to `build/iska_view/` and returns the path."""
    t = player.t if t_ms is None else t_ms
    bg = iska.rgb_to_565(*player.backdrop_rgb())
    img = to_image(clips.frame(player.name, t, bg), clips.width, clips.height,
                   max(1, args.scale))
    out_dir = os.path.join("build", "iska_view")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{player.name}_{int(round(t)):05d}.png")
    img.save(path)
    print(f"[iska_view] frame {player.name} t={t:.0f} ms -> {path}")
    return path


def dump_pose(clips: Clips, name: str, t_ms: float) -> None:
    """Prints the world transform of every bone: the engine's `resolve_bones`."""
    anim = clips.anims[name]
    t = iska.anim_time(anim, t_ms)
    world = clips.skeleton.resolve_bones(iska.sample_pose(anim, t))
    print(f"[iska_view] pose {name} t={t:.0f} ms (asked {t_ms:.0f}), "
          f"{len(world)} bones")
    for i, (x, y, angle, scale) in enumerate(world):
        print(f"[iska_view]   bone{i:2d} pos=({x:+8.3f},{y:+8.3f}) "
              f"angle={angle:+8.3f} scale=({scale[0]:.4f},{scale[1]:.4f})")


def selftest(clips: Clips, args) -> None:
    """Renders frames of every animation with no window (terminal / CI)."""
    if args.out and Image is None:
        raise SystemExit("Pillow is required to write the sheet: pip install pillow")
    bg = iska.rgb_to_565(16, 17, 22)
    scale = max(1, args.scale)
    columns = 4
    tiles = []
    failures = 0
    for name in clips.names:
        anim = clips.anims[name]
        count = max(1, args.selftest)
        frames = []
        for i in range(count):
            t = anim["duration"] * i / count
            buf = clips.frame(name, t, bg)
            frames.append((t, buf, Clips.painted(buf, bg)))
        empty = [t for t, _buf, painted in frames if painted == 0]
        # An empty frame is only a failure **inside** the animation: a one-shot
        # legitimately starts (or ends) with the character off-frame -- the same
        # rule as tools/iska_clip_check.py.
        interior = [t for t in empty if 0.0 < t < float(anim["duration"])]
        failures += 1 if interior else 0
        painted_min = min(painted for _t, _b, painted in frames)
        painted_max = max(painted for _t, _b, painted in frames)
        if interior:
            verdict = f"EMPTY frame(s) at {interior} ms"
        elif empty:
            verdict = f"OK (off-frame at {empty} ms, allowed)"
        else:
            verdict = "OK"
        print(f"[iska_view] selftest {name}: {count} frames, painted "
              f"{painted_min}..{painted_max} px -> {verdict}")
        tiles += [(name, t, buf) for t, buf, _p in frames]

    if args.out and tiles:
        rows = (len(tiles) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * clips.width * scale, rows * clips.height * scale),
                          (10, 10, 14))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(sheet)
        for i, (name, t, buf) in enumerate(tiles):
            tile = to_image(buf, clips.width, clips.height, scale)
            x = (i % columns) * clips.width * scale
            y = (i // columns) * clips.height * scale
            sheet.paste(tile, (x, y))
            draw.rectangle([x, y, x + tile.size[0] - 1, y + tile.size[1] - 1],
                           outline=(60, 60, 70))
            draw.text((x + 4, y + 4), f"{name} t={t:.0f} ms", fill=(255, 240, 120))
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        sheet.save(args.out)
        print(f"[iska_view] {len(tiles)} frames -> {args.out} "
              f"({sheet.size[0]}x{sheet.size[1]})")

    if failures:
        raise SystemExit(f"[iska_view] {failures} empty frame(s): the asset is broken")


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #

def run_window(clips: Clips, player: Player, args) -> None:
    """Opens the window: the panel, two text lines, and the keyboard."""
    import tkinter as tk

    scale = max(1, args.scale)
    width, height = clips.width * scale, clips.height * scale
    bar = 34
    state = {"photo": None, "image": None, "render": time.perf_counter(), "fps": 0.0}

    root = tk.Tk()
    root.title(f"Intellar ISKA - {os.path.basename(args.iska)}")
    if args.topmost:
        root.attributes("-topmost", True)
    canvas = tk.Canvas(root, width=width, height=height + bar, highlightthickness=0,
                       bg="#05060a")
    canvas.pack()
    canvas.create_rectangle(0, height, width, height + bar, fill="#05060a",
                            outline="")
    status = canvas.create_text(6, height + 9, anchor="w", fill="#ffe888",
                                font=("Consolas", 9))
    canvas.create_text(6, height + 25, anchor="w", fill="#8890a0",
                       font=("Consolas", 8), text=HELP_KEYS)

    def redraw() -> None:
        bg = iska.rgb_to_565(*player.backdrop_rgb())
        img = to_image(clips.frame(player.name, player.t, bg), clips.width,
                       clips.height, scale)
        if state["photo"] is not None and ImageTk is not None:
            state["photo"].paste(img)      # in place: no allocation per frame
        else:
            state["photo"] = make_photo(img)
            if state["image"] is None:
                state["image"] = canvas.create_image(0, 0, anchor="nw",
                                                     image=state["photo"])
            else:
                canvas.itemconfig(state["image"], image=state["photo"])
        canvas.itemconfig(status, text=player.status(state["fps"]))

    def on_key(event) -> None:
        key = event.keysym
        if key in ("q", "Escape"):
            root.destroy()
            return
        if key == "space":
            player.playing = not player.playing
            player.clock = time.perf_counter()
        elif key == "Left":
            player.shift(-1)
        elif key == "Right":
            player.shift(1)
        elif key == "Up":
            player.speed = min(8.0, player.speed * 2.0)
        elif key == "Down":
            player.speed = max(0.125, player.speed / 2.0)
        elif key in ("0", "KP_0"):
            player.speed = 1.0
        elif key == "comma":
            player.playing = False
            player.step(-STEP_MS)
        elif key == "period":
            player.playing = False
            player.step(STEP_MS)
        elif key == "bracketleft":
            player.playing = False
            player.step(-BIG_STEP_MS)
        elif key == "bracketright":
            player.playing = False
            player.step(BIG_STEP_MS)
        elif key == "Home":
            player.playing = False
            player.step(-player.t)
        elif key == "l":
            player.loop = not player.loop
        elif key == "b":
            player.backdrop = (player.backdrop + 1) % len(BACKDROPS)
        elif key == "s":
            save_png(clips, player, args)
        redraw()

    def tick() -> None:
        """Real time, not frame counting: the animation never drifts."""
        player.tick()
        now = time.perf_counter()
        interval = 1.0 / (args.max_fps if args.max_fps > 0 else 1000.0)
        if now - state["render"] >= interval:
            dt = max(1e-6, now - state["render"])
            state["render"] = now
            state["fps"] = 0.8 * state["fps"] + 0.2 * (1.0 / dt)
            redraw()
        root.after(10, tick)

    root.bind("<Key>", on_key)
    canvas.bind("<Button-1>", lambda _event: (player.trigger(), redraw()))
    canvas.focus_set()
    redraw()
    tick()
    root.mainloop()
    print("[iska_view] window closed")


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("iska", nargs="?", default=ASSET_DEFAULT,
                    help=f"asset to play (default: {ASSET_DEFAULT})")
    ap.add_argument("--anim", default=None, help="animation to start with")
    ap.add_argument("--scale", type=int, default=3, help="window zoom (default 3)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--loop", action="store_true",
                    help="loop the current animation even if it is a one-shot")
    ap.add_argument("--auto", type=float, default=0.0, metavar="MS",
                    help="replay the one-shot every MS (like the robot's touch)")
    ap.add_argument("--bg", choices=[name for name, _rgb in BACKDROPS], default="dark")
    ap.add_argument("--max-fps", type=int, default=30,
                    help="redraw limit (0 = unlimited; rendering stays exact)")
    ap.add_argument("--topmost", action="store_true", help="keep the window on top")
    ap.add_argument("--selftest", type=int, default=0, metavar="N",
                    help="render N frames per animation and exit (no window)")
    ap.add_argument("--pose", type=float, default=None, metavar="MS",
                    help="print the world transform of every bone at MS, then exit")
    ap.add_argument("--out", default=None,
                    help="PNG: contact sheet (--selftest) or frame (--pose)")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    if not os.path.isfile(args.iska):
        raise SystemExit(f"no such asset: {args.iska}")
    if args.scale < 1:
        raise SystemExit("--scale must be >= 1")

    with open(args.iska, "rb") as fh:
        data = iska.parse_iska(fh.read())
    clips = Clips(data)
    print(f"[iska_view] {args.iska}: {clips.describe()}")
    for i, name in enumerate(clips.names, 1):
        anim = clips.anims[name]
        print(f"[iska_view]   {i}. {name:12s} "
              f"{'loop' if anim['loop'] else 'once':4s} {anim['duration']:5d} ms, "
              f"{len(anim['keys'])} keys")

    player = Player(clips, args.anim or "", speed=args.speed, loop=args.loop,
                    auto_ms=args.auto)
    player.backdrop = [name for name, _rgb in BACKDROPS].index(args.bg)

    if args.pose is not None:
        dump_pose(clips, player.name, args.pose)
        if args.out:
            save_png(clips, player, args, args.pose)
        return
    if args.selftest:
        selftest(clips, args)
        return
    if Image is None:
        raise SystemExit("Pillow is required to display the frames: pip install pillow")
    scale = max(1, args.scale)
    print(f"[iska_view] {clips.width * scale}x{clips.height * scale} window "
          f"(x{scale}, {args.max_fps} fps max)")
    print(f"[iska_view] {HELP_KEYS}")
    run_window(clips, player, args)


if __name__ == "__main__":
    main()
