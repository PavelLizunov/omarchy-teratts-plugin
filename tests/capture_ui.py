#!/usr/bin/env python3
"""Render actual plugin controls offscreen; no desktop input or production I/O.

Based on MX Ergo's installed QtTest capture workflow. Host surfaces, processes
and catalog I/O are replaced only in a temporary fixture. Production layouts,
handlers, catalogs and the installed shell controls remain the input. Captures
are not evidence for Wayland focus, real IPC or server behavior.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent


def prepare(directory, shell, light=False):
    for name in ("Commons", "Ui"):
        shutil.copytree(shell / name, directory / "qs" / name)
    for name, boundary in (("Style", "  property Process hyprctlProc:"),
                           ("Color", "  property FileView colorsFile:")):
        path = directory / "qs/Commons" / (name + ".qml")
        source = path.read_text()
        if boundary not in source:
            raise RuntimeError("Installed shell structure changed: " + name)
        source = source[:source.index(boundary)] + "}\n"
        source = re.sub(r"^import Quickshell(?:\.Io)?\n", "", source, flags=re.M)
        source = re.sub(r'Quickshell\.env\("[A-Z_]+"\)', '""', source)
        if light and name == "Color":
            source = source.replace('property color foreground: "#cacccc"',
                                    'property color foreground: "#232522"')
            source = source.replace('property color background: "#101315"',
                                    'property color background: "#f7f7f2"')
            source = source.replace('property color accent: "#cacccc"',
                                    'property color accent: "#345030"')
        path.write_text(source)
    util = directory / "qs/Commons/Util.qml"
    util.write_text(re.sub(r"^import Quickshell\n", "", util.read_text(), flags=re.M))
    (directory / "qs/Ui/Panel.qml").write_text('''import QtQuick
Item {
  property QtObject bar: null
  property string moduleName: ""
  property string ipcTarget: ""
  property bool manageIpc: false
  property var settings: ({locale:"ru"})
  property bool opened: false
  function open() { opened = true }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }
}
''')
    # Retain the installed host's fitting contract while replacing its window.
    keyboard_panel = (shell / "Ui/KeyboardPanel.qml").read_text()
    sizing = keyboard_panel[keyboard_panel.index("  function fittedContentWidth("):
                            keyboard_panel.index("  // Desired top-left")]
    (directory / "qs/Ui/KeyboardPanel.qml").write_text('''import QtQuick
import qs.Commons
Item {
  id: root
  property Item anchorItem: null
  property var owner: null
  property QtObject bar: null
  property bool open: false
  property Item focusTarget: null
  property int contentWidth: 380
  property int contentHeight: 540
  property real availableCardWidth: 380
  property real availableCardHeight: 540
  property int padding: Style.spacing.popupPadding
  property var borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
  readonly property real verticalContentInset: padding * 2 + Border.top(borderSpec) + Border.bottom(borderSpec)
  default property alias contentItem: holder.children
  width: contentWidth
  height: contentHeight
HOST_SIZING
  BorderSurface {
    id: card
    anchors.fill: parent
    color: Color.popups.background
    borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
    padding: Style.spacing.popupPadding
    radius: Style.cornerRadius
    Item {
      id: holder
      anchors.fill: parent
      anchors.leftMargin: card.contentLeftInset
      anchors.rightMargin: card.contentRightInset
      anchors.topMargin: card.contentTopInset
      anchors.bottomMargin: card.contentBottomInset
    }
  }
}
'''.replace("HOST_SIZING", sizing))
    plugin = directory / "plugin"
    plugin.mkdir()
    shutil.copytree(ROOT / "assets", plugin / "assets")
    panel = (ROOT / "Panel.qml").read_text()
    panel = re.sub(r"^import Quickshell(?:\.Io)?\n", "", panel, flags=re.M)
    panel = re.sub(r"(\bid:\s*([A-Za-z_]\w*)\s*\n)",
                   lambda m: m[1] + '    objectName: "' + m[2] + '"\n', panel)
    (plugin / "TeraPanel.qml").write_text(panel)
    bar = (ROOT / "BarWidget.qml").read_text().replace("import Quickshell.Io\n", "")
    bar = bar.replace('source: Qt.resolvedUrl("Panel.qml")', 'source: Qt.resolvedUrl("TeraPanel.qml")')
    bar = re.sub(r"(\bid:\s*([A-Za-z_]\w*)\s*\n)",
                 lambda m: m[1] + '    objectName: "' + m[2] + '"\n', bar)
    (plugin / "TeraBar.qml").write_text(bar)
    (plugin / "IpcHandler.qml").write_text('import QtQml\nQtObject { property string target: "" }\n')
    stream = (ROOT / "StateStream.qml").read_text().replace("import Quickshell.Io\n", "")
    stream = re.sub(r"(\bid:\s*([A-Za-z_]\w*)\s*\n)",
                    lambda m: m[1] + '    objectName: "' + m[2] + '"\n', stream)
    (plugin / "StateStream.qml").write_text(stream)
    shutil.copy(ROOT / "TeraIcon.qml", plugin)
    i18n = (ROOT / "I18n.qml").read_text().replace("import Quickshell.Io\n", "")
    i18n = i18n[:i18n.index("  property FileView englishFile:")] + "}\n"
    for name, locale in (("english", "en"), ("russian", "ru")):
        catalog = json.loads((ROOT / "locales" / (locale + ".json")).read_text())
        i18n = i18n.replace("property var " + name + ": ({})",
                            "property var " + name + ": (" + json.dumps(catalog, ensure_ascii=False) + ")")
    (plugin / "I18n.qml").write_text(i18n)
    (plugin / "Process.qml").write_text('''import QtQuick
Item {
  property var command: []
  property var environment: ({})
  property bool running: false
  property bool stdinEnabled: false
  property QtObject stdout: null
  property QtObject stderr: null
  property string input: ""
  property var calls: []
  signal started()
  signal exited(int exitCode, int exitStatus)
  onRunningChanged: if (running) { calls = calls.concat([command]); started() }
  function write(value) { input += value }
  function finish(code, status, out, err) {
    if (stdout && "text" in stdout) stdout.text = out || ""
    if (stderr && "text" in stderr) stderr.text = err || ""
    exited(code, status)
    running = false
  }
  function signal(value) { running = false }
}
''')
    (plugin / "StdioCollector.qml").write_text('''import QtQml
QtObject { property bool waitForEnd: false; property string text: "" }
''')
    (plugin / "SplitParser.qml").write_text('''import QtQml
QtObject { signal read(string line) }
''')
    # Qt 6.12's Color type shadows the host palette; include generated adapters.
    for path in directory.rglob("*.qml"):
        source = re.sub(r"^(\s*)import (QtQuick(?:\.Window)?)\s*$",
                        r"\1import \2 6.11", path.read_text(), flags=re.M)
        path.write_text(source)
    return plugin


def prepare_preview(directory, shell, light=False):
    """Prepare the reviewed MCP import root without running project operations."""
    prepare(directory, shell, light)
    # Native Quickshell resolves qs imports from shell.qml's sibling modules.
    for name in ("Commons", "Ui"):
        shutil.copytree(directory / "qs" / name, directory / name)
    (directory / "shell.qml").write_text('import QtQuick 6.11\nItem {}\n')
    shutil.copy(ROOT / "tests/ui/preview.qml", directory / "fixture.qml")
    shutil.copy(ROOT / "tests/ui/icon_context.qml", directory / "icon_context.qml")
    # Hash both import trees: QtTest and the native adapter can resolve either.
    dependencies = [str(path.resolve()) for path in directory.rglob("*")
                    if path.is_file()
                    and (path.suffix in (".qml", ".js", ".svg", ".png") or path.name == "qmldir")]
    dependencies += [str(ROOT / name) for name in
                     ("Panel.qml", "BarWidget.qml", "I18n.qml", "StateStream.qml", "TeraIcon.qml",
                      "locales/en.json", "locales/ru.json", "tests/capture_ui.py",
                      "tests/ui/preview.qml", "tests/ui/tst_panel.qml", "tests/ui/icon_context.qml")]
    (directory / "dependencies.json").write_text(json.dumps(dependencies, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shell", type=Path, default=Path("/usr/share/omarchy/shell"))
    parser.add_argument("--prepare-preview", action="store_true",
                        help="Prepare an inert MCP fixture in a new output directory; do not run tests")
    parser.add_argument("--light", action="store_true", help="Use an initial synthetic light palette")
    args = parser.parse_args()
    if args.light and not args.prepare_preview:
        parser.error("--light requires --prepare-preview")
    if args.prepare_preview:
        args.output.mkdir(parents=True, exist_ok=False)
        prepare_preview(args.output.resolve(), args.shell, args.light)
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix="teratts-ui-") as temporary:
        directory = Path(temporary)
        plugin = prepare(directory, args.shell)
        source = (ROOT / "tests/ui/tst_panel.qml").read_text()
        source = source.replace('"PLUGIN_PATH"', json.dumps(plugin.as_uri()))
        source = source.replace('"CAPTURE_PATH"', json.dumps(str(output)))
        inputs = directory / "input"
        inputs.mkdir()
        (inputs / "tst_panel.qml").write_text(source)
        result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-import", str(directory),
                                 "-input", str(inputs)], timeout=45,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                     "QT_QPA_PLATFORMTHEME": "generic", "QT_STYLE_OVERRIDE": "Fusion",
                                     "QT_QUICK_BACKEND": "software"})
        inputs_hash = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (ROOT / "Panel.qml", ROOT / "I18n.qml", ROOT / "TeraIcon.qml",
                                 ROOT / "StateStream.qml", ROOT / "BarWidget.qml",
                                 ROOT / "tests/capture_ui.py",
                                 ROOT / "tests/ui/tst_panel.qml", ROOT / "locales/ru.json",
                                 ROOT / "locales/en.json")}
        (output / "capture-inputs.json").write_text(json.dumps({
            "source_hashes": inputs_hash, "shell": str(args.shell), "exit_code": result.returncode,
            "host_sizing_sha256": hashlib.sha256(
                (args.shell / "Ui/KeyboardPanel.qml").read_bytes()).hexdigest(),
            "platform": "offscreen", "backend": "software", "scale": 2,
            "limits": ["fixture data", "inert processes and host surface", "no native focus/IPC proof"]
        }, indent=2))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
