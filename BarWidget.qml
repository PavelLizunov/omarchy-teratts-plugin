import QtQuick 6.11
import Quickshell.Io
import qs.Commons
import qs.Commons as Host
import "." as Local
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.pavellizunov.teratts"

  Local.I18n {
    id: i18n
    language: String(root.settings?.locale || "ru")
  }

  readonly property var liveState: stateStream.liveState
  readonly property bool speaking: stateStream.connected && liveState.speaking === true
  readonly property bool busy: liveState.busy === true
  readonly property bool paused: liveState.status === "paused" || liveState.pauseRequested === true

  function localPath(url) {
    var value = String(url)
    return value.indexOf("file://") === 0 ? decodeURIComponent(value.slice(7)) : value
  }
  readonly property string speakBin: localPath(Qt.resolvedUrl("bin/speak"))

  IpcHandler {
    objectName: "runtimeStatus"
    target: root.moduleName + ".status"
    function status(): string {
      return JSON.stringify({version: "0.3.17", source: String(Qt.resolvedUrl(".")),
        connected: stateStream.connected, playback: root.liveState.status,
        busy: root.busy, panelLoaded: panelLoader.status === Loader.Ready,
        opened: root.opened})
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // The bar host injects `bar` and `settings` into the widget, not into the
  // panel it loads, so they have to be handed down by hand.
  function injectPanel() {
    var p = panelLoader.item
    if (!p)
      return
    if ("bar" in p)
      p.bar = root.bar
    if ("settings" in p)
      p.settings = root.settings
    if ("anchorItem" in p)
      p.anchorItem = button
    if ("hostWidget" in p)
      p.hostWidget = root
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  // Shape the bar expects when routing summon/hide to a widget's panel.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() {
    if (!tabProc.running)
      tabProc.running = true
  }
  function close() {
    if (panelLoader.item)
      panelLoader.item.close()
  }
  function toggle() {
    if (panelLoader.item)
      panelLoader.item.toggle()
  }
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() {
    if (panelLoader.item)
      panelLoader.item.closeForPopoutSwitch()
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  StateStream {
    id: stateStream
    executable: root.speakBin
  }

  Process {
    id: tabProc
    command: [root.speakBin, "--consume-ui-request"]
    stdout: StdioCollector {
      id: tabOut
      waitForEnd: true
    }
    onExited: function (code, status) {
      var page = "read"
      try {
        if (code === 0 && JSON.parse(tabOut.text).tab === "audio")
          page = "audio"
      } catch (e) {}
      if (panelLoader.item)
        panelLoader.item.openPage(page)
    }
  }

  Process {
    id: runner
    environment: ({TTS_UI_LOCALE: i18n.locale})
    running: false
    command: []
  }

  function run(args) {
    // Only the idempotent quick toggle uses this runner. Replacing an older
    // invocation is intentional; the CLI owns the provider transition.
    runner.running = false
    runner.command = [root.speakBin].concat(args)
    runner.running = true
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    fixedWidth: vertical ? -1 : Style.bar.iconSlot
    fixedHeight: vertical ? Style.bar.iconSlot : -1
    horizontalMargin: 0
    verticalPadding: 0
    active: root.busy
    tooltipText: i18n.text("bar.state." + (root.paused ? "paused" : root.liveState.status))

    onPressed: function (btn) {
      if (btn === Qt.RightButton) {
        // Quick action, so speaking never requires opening the panel first.
        root.run(["--quick-action"])
      } else {
        root.toggle()
      }
    }

    TeraIcon {
      anchors.centerIn: parent
      color: !stateStream.connected ? Host.Color.urgent : button.active && button.useActiveColor ? button.activeColor : button.foreground
      iconSize: Style.bar.iconCanvas
      playing: root.speaking
      levels: root.liveState.bands || [0, 0, 0, 0]
      busy: ["preparing", "buffering", "exporting"].indexOf(root.liveState.status) >= 0
    }
  }
}
