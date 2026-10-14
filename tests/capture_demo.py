#!/usr/bin/env python3
"""Silent actual-panel Qt navigation demo; inert I/O, no desktop or remote service."""
from pathlib import Path
import argparse
import json
import os
import struct
import subprocess
import tempfile

from capture_ui import prepare

ROOT = Path(__file__).resolve().parents[1]

DEMO = '''
  function test_public_navigation_demo() {
    panel.settings = {locale:"en"}
    panel.sampleText = "A short TeraTTS test."
    var serial = 0
    function frame() {
      wait(40)
      var name = String(serial++).padStart(3, "0")
      var image = grabImage(surface)
      image.save(output + "/frame-" + name + ".png")
    }
    function hold(count) { for (var i = 0; i < count; i++) frame() }
    page("read"); hold(6)
    mouseClick(button("Files")); hold(6)
    mouseClick(control("createToggle")); hold(5)
    mouseClick(button("Settings")); panel.selectSettings("voice"); hold(5)
    mouseClick(button("Server")); hold(6)
    mouseClick(button("Read")); hold(5)
    widget.liveState = {status:"playing",speaking:true,kind:"speech",busy:true,playbackRate:1.25,bands:[0,0,0,0]}
    for (var i = 0; i < 12; i++) {
      widget.liveState = {status:"playing",speaking:true,kind:"speech",busy:true,playbackRate:1.25,
        bands:i % 2 ? [.1,.3,.15,.1] : [.25,.7,.4,.6]}
      frame()
    }
    widget.liveState = {status:"paused",speaking:false,kind:"speech",busy:true,playbackRate:1.25}
    hold(5)
    widget.liveState = {status:"idle",busy:false}
    hold(4)
    console.log("DEMO_FRAMES " + serial)
  }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shell", type=Path, default=Path("/usr/share/omarchy/shell"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="teratts-demo-") as directory:
        root = Path(directory)
        plugin = prepare(root, args.shell)
        source = (ROOT / "tests/ui/tst_panel.qml").read_text()
        source = source.replace('"PLUGIN_PATH"', json.dumps(plugin.as_uri()))
        source = source.replace('"CAPTURE_PATH"', json.dumps(str(args.output.resolve())))
        assert source.endswith("}\n")
        source = source[:-2] + DEMO + "}\n"
        inputs = root / "input"
        inputs.mkdir()
        (inputs / "tst_demo.qml").write_text(source)
        result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-import", str(root), "-input", str(inputs),
                                 "TeraPanelOffscreen::test_public_navigation_demo"], timeout=30,
                                env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "QT_QPA_PLATFORMTHEME":"generic",
                                     "QT_STYLE_OVERRIDE":"Fusion", "QT_QUICK_BACKEND":"software"})
        if result.returncode:
            return result.returncode
        frames = sorted(args.output.glob("frame-*.png"))
        assert [p.name for p in frames] == [f"frame-{i:03}.png" for i in range(54)]
        for frame in frames:
            data = frame.read_bytes()
            assert data.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack(
                ">II", data[16:24]) == (380, 540), frame
        print("Verified 54 actual-panel PNG frames at 380x540.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
