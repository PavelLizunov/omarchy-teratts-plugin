pragma ComponentBehavior: Bound
import QtQuick 6.11

Item {
  id: root
  property int iconSize: 24
  property color color: "white"
  property bool playing: false
  property bool busy: false
  property var levels: [0, 0, 0, 0]
  width: iconSize
  height: iconSize
  readonly property real unit: iconSize / 16

  Rectangle {
    objectName: "monogramCrown"
    x: root.unit
    y: root.unit
    width: 6 * root.unit
    height: root.unit
    color: root.color
  }
  Rectangle {
    objectName: "monogramShoulder"
    x: 0
    y: 2 * root.unit
    width: 8 * root.unit
    height: 2 * root.unit
    color: root.color
  }
  Rectangle {
    objectName: "monogramStem"
    x: 3 * root.unit
    y: 4 * root.unit
    width: 3 * root.unit
    height: 10 * root.unit
    color: root.color
  }
  Rectangle {
    objectName: "monogramFoot"
    x: 3 * root.unit
    y: 14 * root.unit
    width: 2 * root.unit
    height: root.unit
    color: root.color
  }

  Repeater {
    model: 4
    delegate: Rectangle {
      id: soundBar
      required property int index
      readonly property real level: {
        var value = Number(root.levels && root.levels[index])
        return root.playing && isFinite(value) ? Math.max(0, Math.min(1, value)) : 0
      }
      readonly property real restingHeight: [4, 8, 6, 4][index]
      x: (8 + index * 2) * root.unit
      y: 8 * root.unit - height / 2
      width: root.unit
      height: (root.playing ? 1.5 + level * 8.5 : restingHeight) * root.unit
      color: root.color

      Behavior on height {
        NumberAnimation { duration: 80 }
      }
    }
  }

  Rectangle {
    id: busyDot
    objectName: "busyMarker"
    visible: root.busy
    x: 13 * root.unit
    y: 13 * root.unit
    width: 2 * root.unit
    height: width
    color: root.color
    SequentialAnimation on opacity {
      running: root.busy && root.visible
      loops: Animation.Infinite
      NumberAnimation { from: 1; to: .35; duration: 500 }
      NumberAnimation { from: .35; to: 1; duration: 500 }
    }
  }
}
