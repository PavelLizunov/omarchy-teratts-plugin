import QtQuick
import Quickshell.Io

// Own one subscriber per widget. Timed retries cover failed starts as well as
// exits; the helper heartbeat distinguishes healthy silence from a lost stream.
Item {
  id: root
  visible: false
  required property string executable
  property var liveState: ({status: "unavailable", busy: false, speaking: false, bands: [0, 0, 0, 0]})
  property bool connected: false
  property int retryDelay: 2000
  property bool stopping: false

  function lost() {
    connected = false
    liveState = {status: "unavailable", busy: false, speaking: false, bands: [0, 0, 0, 0]}
    watchdog.stop()
    if (!retryTimer.running)
      retryTimer.start()
  }

  Process {
    id: subscriber
    command: [root.executable, "--watch-state"]
    onRunningChanged: {
      if (running && !root.stopping)
        watchdog.restart()
      else if (!running) {
        escalation.stop()
        root.stopping = false
        root.lost()
      }
    }
    onExited: root.lost()
    stdout: SplitParser {
      onRead: function (line) {
        if (root.stopping)
          return
        try {
          var next = JSON.parse(line)
          if (["idle", "preparing", "playing", "paused", "buffering", "exporting", "error"].indexOf(next.status) < 0 || typeof next.busy !== "boolean" || typeof next.speaking !== "boolean")
            return
          root.liveState = next
          root.connected = true
          root.retryDelay = 2000
          retryTimer.stop()
          watchdog.restart()
        } catch (e) {}
      }
    }
  }
  Timer {
    id: watchdog
    interval: 8000
    onTriggered: {
      root.stopping = subscriber.running
      subscriber.running = false
      root.lost()
      if (subscriber.running)
        escalation.start()
    }
  }
  Timer {
    id: retryTimer
    interval: root.retryDelay
    onTriggered: {
      if (subscriber.running)
        return
      root.retryDelay = Math.min(30000, root.retryDelay * 2)
      subscriber.running = true
      // A failed start need not emit exited/runningChanged on every host.
      watchdog.restart()
    }
  }
  Timer {
    id: escalation
    interval: 2000
    onTriggered: if (root.stopping && subscriber.running) subscriber.signal(9)
  }
  Component.onCompleted: {
    subscriber.running = true
    watchdog.start()
  }
}
