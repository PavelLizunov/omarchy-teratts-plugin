import QtQuick 6.11
import qs.Commons as Host
import qs.Ui as Native
import "plugin" as Plugin

// Actual icon/bar consumers with inert I/O; neighbor glyphs use the host font.
Rectangle {
  id: fixture
  objectName: "iconContext"
  width: 700
  height: 220
  color: Host.Color.bar.background
  property bool ready: false
  property var glyphs: []
  property var states: [
    {label:"Idle",status:"idle",busy:false,speaking:false,bands:[0,0,0,0]},
    {label:"Silent playback",status:"playing",busy:true,speaking:true,bands:[0,0,0,0]},
    {label:"Speech",status:"playing",busy:true,speaking:true,bands:[.2,.8,.5,.9]},
    {label:"Full",status:"playing",busy:true,speaking:true,bands:[1,1,1,1]},
    {label:"Paused",status:"paused",busy:true,speaking:false,bands:[0,0,0,0]},
    {label:"Preparing",status:"preparing",busy:true,speaking:false,bands:[0,0,0,0]}
  ]
  function find(item, name) {
    if (item.objectName === name) return item
    for (var i=0;i<(item.children || []).length;i++) {
      var found=find(item.children[i],name)
      if (found) return found
    }
    return null
  }
  function settled(icon) {
    var bars=icon.children.filter(function(item) { return typeof item.index === "number" })
    return bars.length === 4 && bars.every(function(bar) {
      var height=icon.playing ? 1.5+bar.level*8.5 : bar.restingHeight
      return Math.abs(bar.height-height*icon.unit)<.01
    })
  }
  Text {
    x:16;y:12
    text:"TeraTTS · native bar context and resting waveform"
    color:Host.Color.bar.text;font.family:Host.Style.font.family;font.pixelSize:14
    textFormat:Text.PlainText
  }
  Row {
    x:16;y:44
    Native.BarIconButton {text:"\uf075";foreground:Host.Color.bar.text}
    Native.BarIconButton {text:"\uf07b";foreground:Host.Color.bar.text}
    Native.BarIconButton {text:"\uf025";foreground:Host.Color.bar.text}
    Native.WidgetButton {
      objectName:"contextSlot"
      fixedWidth:Host.Style.bar.iconSlot
      horizontalMargin:0;verticalPadding:0;labelVisible:false;hasVisualContent:true
      Plugin.TeraIcon {
        iconSize:Host.Style.bar.iconCanvas
        color:Host.Color.bar.text
        anchors.centerIn:parent
      }
    }
    Native.BarIconButton {text:"\uf16b";foreground:Host.Color.bar.text}
    Native.BarIconButton {text:"\uf0e7";foreground:Host.Color.bar.text}
    Native.BarIconButton {text:"\uf028";foreground:Host.Color.bar.text}
    Native.BarIconButton {text:"\uf108";foreground:Host.Color.bar.text}
  }
  Text {
    x:16;y:86
    text:"16-unit canvas above; 3× details below. Resting shape is not a sound-level reading."
    color:Host.Color.bar.text;font.family:Host.Style.font.family;font.pixelSize:10
    textFormat:Text.PlainText
  }
  Row {
    x:16;y:111;spacing:14
    Repeater {
      model:fixture.states
      delegate: Column {
        required property var modelData
        required property int index
        width:96;spacing:7
        Plugin.TeraBar {
          width:implicitWidth;height:implicitHeight
          objectName:"stateSlot"+index
          anchors.horizontalCenter:parent.horizontalCenter
          settings:({locale:"en"})
          Component.onCompleted: {
            var stream=fixture.find(this,"stateStream")
            stream.liveState=modelData
            stream.connected=true
            var button=fixture.find(this,"button")
            fixture.glyphs=fixture.glyphs.concat([button.children.find(function(item) { return item.levels !== undefined })])
          }
        }
        Text {
          width:parent.width;text:modelData.label;horizontalAlignment:Text.AlignHCenter
          color:Host.Color.bar.text;font.family:Host.Style.font.family;font.pixelSize:9
          textFormat:Text.PlainText
        }
        Plugin.TeraIcon {
          iconSize:48;anchors.horizontalCenter:parent.horizontalCenter
          color:Host.Color.bar.text;playing:modelData.speaking;levels:modelData.bands
          busy:modelData.status === "preparing"
          Component.onCompleted:fixture.glyphs=fixture.glyphs.concat([this])
        }
      }
    }
  }
  Timer {
    interval:50;repeat:true;running:true
    onTriggered: if (fixture.glyphs.length === 12 && fixture.glyphs.every(fixture.settled)) {
      fixture.ready=true
      stop()
    }
  }
}
