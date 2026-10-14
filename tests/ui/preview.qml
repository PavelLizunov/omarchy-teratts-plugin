import QtQuick 6.11
import qs.Commons
import "plugin" as Plugin

// Actual panel and installed native controls; synthetic state and inert I/O.
Rectangle {
  id: fixture
  width: 380
  height: 540
  color: Color.popups.background
  property string localeCode: "ru"
  property string page: "read"
  property string settingsPage: "voice"
  property string status: "idle"
  property string kind: "speech"
  property string stopChord: "SUPER + ALT + X"
  property bool empty: false
  property bool createFile: false
  property bool failure: false
  property bool localOcr: false
  property bool editor: false
  property bool tokenEditor: false
  property bool loading: false
  property bool ready: false
  property real availableHeight: 540
  property real availableWidth: 380

  QtObject {
    id: model
    property var liveState: ({status:fixture.status,kind:fixture.kind,
      busy:fixture.status !== "idle" && fixture.status !== "error",
      speaking:fixture.status === "playing",
      audioId:fixture.kind === "preview" ? "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" : null,
      durationMs:30000,positionMs:12000,playbackRate:1.25})
    property bool speaking: liveState.speaking
  }
  Plugin.TeraPanel {
    id: panel
    width: parent.width
    height: parent.height
    hostWidget: model
    settings: ({locale:fixture.localeCode})
    infoLoaded: !fixture.loading
    infoBusy: fixture.loading
    info: ({provider:"teratts",voice:"ru_f1",rate:1.25,endpoint:"https://tts.example.test",
      voices:[{value:"ru_f1",label:"Russian Female 1"},{value:"ru_m1",label:"Russian Male 1"}],
      ui:{exportFormat:"mp3",sampleIsDefault:true},
      ocr:{engine:fixture.localOcr ? "tesseract" : "remote",remoteEndpoint:"https://ocr.example.test",
        langs:"rus+eng",languages:[{value:"eng",label:"English",installed:true},{value:"rus",label:"Russian",installed:true}],
        engines:[{name:"remote",title:"Remote OCR",status:"ready",kind:"remote"},{name:"tesseract",title:"Tesseract",status:"ready",kind:"local"}]}})
    bindingInfoLoaded: true
    bindingInfo: ({installed:true,conflicts:[],bindings:{selection:{chord:"SUPER + ALT + E"},stop:{chord:fixture.stopChord}}})
    panelPage: fixture.page
    settingsPage: fixture.settingsPage
    audioCreateOpen: fixture.createFile
    keyEditing: fixture.tokenEditor
    bindingAction: fixture.editor ? "stop" : ""
    bindingDraft: fixture.stopChord
    error: fixture.failure ? "The server request failed. Check the connection and retry." : ""
    audioItems: fixture.empty ? [] : [
      {id:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",filename:"teratts-20261012T142500Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp3",createdAt:"2026-10-12T14:25:00Z",durationMs:30000,voice:"ru_f1",rate:1.25,bytes:16000},
      {id:"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",filename:"teratts-20261012T141000Z-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.ogg",createdAt:"2026-10-12T14:10:00Z",durationMs:62000,voice:"ru_m1",rate:1,bytes:24000}]
  }
  function find(item, name) {
    if (item.objectName === name) return item
    for (var i = 0; i < (item.children || []).length; i++) {
      var found = find(item.children[i], name)
      if (found) return found
    }
    return null
  }
  Timer {
    interval: 80
    running: true
    onTriggered: {
      var card = find(panel, "panelCard")
      card.availableCardHeight = fixture.availableHeight
      card.availableCardWidth = fixture.availableWidth
      if (fixture.empty)
        find(panel, "audioListProc").finish(0, 0, "[]", "")
      if (fixture.editor) {
        find(panel, "chordField").text = fixture.stopChord
        panel.reveal(find(panel, "bindingEditor"))
      }
      if (fixture.tokenEditor)
        panel.reveal(find(panel, "keyField"))
      settled.start()
    }
  }
  Timer { id: settled; interval: 100; onTriggered: fixture.ready = true }
}
