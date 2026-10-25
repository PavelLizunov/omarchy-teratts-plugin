import QtQuick 6.11
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Host
import "." as Local
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.pavellizunov.teratts"
  ipcTarget: moduleName
  manageIpc: false
  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property string ff: bar ? bar.fontFamily : Style.font.family
  property var info: ({
      voice: "ru_f1",
      voices: [],
      rate: 1,
      endpoint: ""
    })
  property bool infoLoaded: false
  property string error: ""
  property string sampleText: i18n.text("sample.text")
  property bool sampleDirty: false
  property string pendingValue: ""
  property string pendingSpeech: ""
  property var queue: []
  property bool refreshQueued: false
  property real rateOverride: -1
  property bool keyEditing: false
  property string pendingKey: ""
  property bool keySaved: false
  property bool voiceBusy: false
  property bool infoBusy: false
  property var bindingInfo: ({
      installed: false,
      bindings: {},
      conflicts: []
    })
  property bool bindingInfoLoaded: false
  property bool bindingBusy: false
  property string bindingAction: ""
  property string bindingDraft: ""
  property bool bindingRecording: false
  property string panelPage: "read"
  property string settingsPage: "voice"
  property bool audioCreateOpen: false
  property bool ocrBusy: false
  property string requestedPage: "read"
  property bool exportMode: false
  property string exportSource: "selection"
  property string exportFormat: "mp3"
  property var audioItems: []
  property bool audioRefreshQueued: false
  property string audioMessage: ""
  property real pendingRate: -1
  property string lastAudioRevision: ""
  property string deleteId: ""
  property string deleteFilename: ""
  property Item editorOwner: null
  property int writeEpoch: 0
  property int readEpoch: 0
  readonly property var playback: hostWidget ? hostWidget.liveState : ({
      status: "idle",
      busy: false
    })
  readonly property bool busy: playback.busy === true
  readonly property bool paused: playback.status === "paused" || playback.pauseRequested === true
  readonly property bool previewing: playback.kind === "preview" && busy
  readonly property var previewItem: audioItems.find(function (item) {
    return item.id === root.playback.audioId
  }) || ({})
  readonly property real previewDuration: Math.max(0, Number(playback.durationMs || previewItem.durationMs || 0) / 1000)
  readonly property real previewPosition: Math.max(0, Number(playback.positionMs || 0) / 1000)
  readonly property real rateValue: rateOverride >= 0 ? rateOverride : busy && playback.playbackRate !== null && playback.playbackRate !== undefined ? Number(playback.playbackRate) : Number(info.rate || 1)
  readonly property bool speaking: hostWidget ? hostWidget.speaking === true : false
  readonly property var activeOcrEngine: (info.ocr?.engines || []).find(function (e) {
    return e.name === (info.ocr?.engine || "tesseract")
  }) || ({})
  readonly property var remoteOcrEngine: (info.ocr?.engines || []).find(function (e) {
    return e.name === "remote"
  }) || ({})
  readonly property var bindingActions: [
    {
      key: "selection",
      fallback: "SUPER + ALT + E"
    },
    {
      key: "clipboard",
      fallback: "SUPER + ALT + A"
    },
    {
      key: "stop",
      fallback: "SUPER + ALT + X"
    },
    {
      key: "snip",
      fallback: "SUPER + ALT + R"
    },
    {
      key: "window",
      fallback: "SUPER + ALT + W"
    },
    {
      key: "screen",
      fallback: "SUPER + ALT + SHIFT + R"
    },
    {
      key: "export",
      fallback: ""
    },
    {
      key: "audio",
      fallback: "SUPER + SHIFT + L"
    },
    {
      key: "pause",
      fallback: ""
    }
  ]

  // Native semantic glyphs supplement labels; they never replace action names.
  readonly property var glyphs: ({
    read:"\uf02d", audio:"\uf1c7", settings:"\uf013", selection:"\uf246", clipboard:"\uf0ea",
    snip:"\uf125", window:"\uf2d0", screen:"\uf108", voice:"\uf130", ocr:"\uf031",
    server:"\uf233", keys:"\uf11c", pause:"\uf04c", play:"\uf04b", stop:"\uf04d",
    export:"\uf019", refresh:"\uf021", copy:"\uf0c5", remove:"\uf1f8", folder:"\uf07c",
    save:"\uf0c7", cancel:"\uf00d", check:"\uf00c", key:"\uf084", speed:"\uf0e4", language:"\uf1ab"
  })
  function shortcutIcon(action) {
    return glyphs[action === "pause" ? "pause" : action] || glyphs.keys
  }

  Local.I18n {
    id: i18n
    language: String(root.settings?.locale || "ru")
    onLocaleChanged: root.updateLocalizedSample()
    onEnglishChanged: root.updateLocalizedSample()
    onRussianChanged: root.updateLocalizedSample()
  }

  onPanelPageChanged: {
    deleteId = ""
    if (panelPage !== "settings")
      keyEditing = false
    if (panelPage !== "settings") {
      bindingAction = ""
      bindingRecording = false
    }
    if (panelPage === "audio")
      refreshAudio()
  }

  function localPath(url) {
    var value = String(url)
    return value.indexOf("file://") === 0 ? decodeURIComponent(value.slice(7)) : value
  }
  readonly property string speakBin: localPath(Qt.resolvedUrl("bin/speak"))
  readonly property string setupBin: localPath(Qt.resolvedUrl("bin/speak-setup"))
  readonly property string bindingsBin: localPath(Qt.resolvedUrl("bin/speak-bindings"))

  function shortcutChord(action) {
    var current = bindingInfo.bindings?.[action.key]?.chord
    return current !== undefined ? String(current) : String(action.fallback)
  }
  readonly property string effectiveStopChord: bindingInfoLoaded && bindingInfo.installed
    && (bindingInfo.conflicts || []).indexOf(bindingInfo.bindings?.stop?.chord) < 0
    ? String(bindingInfo.bindings?.stop?.chord || "") : ""
  function ocrName() {
    return info.ocr?.engine === "remote" ? i18n.text("screen.remoteSource")
      : String(activeOcrEngine.title || info.ocr?.engine || "tesseract")
  }
  function voiceOptions() {
    return (info.voices || []).map(function(voice) {
      var key = "voice.name." + voice.value
      var label = i18n.text(key)
      return {value:String(voice.value), label:label === key ? String(voice.label || voice.value) : label}
    })
  }
  function audioTitle(item) {
    var date = new Date(item.createdAt)
    var title = isNaN(date.getTime()) ? i18n.text("audio.playingFile")
      : date.toLocaleString(Qt.locale(i18n.locale), "d MMM, HH:mm")
    return title + " · " + audioTime(Number(item.durationMs || 0) / 1000)
  }
  function selectPage(page) {
    panelPage = page
    viewport.contentY = 0
  }
  function selectSettings(page) {
    keyEditing = false
    bindingAction = ""
    bindingRecording = false
    settingsPage = page
    selectPage("settings")
  }
  function openPage(page) {
    requestedPage = ["read", "audio", "settings"].indexOf(page) >= 0 ? page : "read"
    if (opened) {
      selectPage(requestedPage)
      if (panelPage === "audio")
        refreshAudio()
    } else
      open()
  }
  function reveal(item) {
    var ancestor = item
    while (ancestor && ancestor !== viewport.contentItem)
      ancestor = ancestor.parent
    if (!ancestor)
      return
    var y = item.mapToItem(viewport.contentItem, 0, 0).y
    if (y < viewport.contentY)
      viewport.contentY = Math.max(0, y)
    else if (y + item.height > viewport.contentY + viewport.height)
      viewport.contentY = Math.min(Math.max(0, viewport.contentHeight - viewport.height), y + item.height - viewport.height)
  }
  function cancelEditor() {
    if (bindingRecording)
      bindingRecording = false
    else if (deleteId) {
      deleteId = ""
      if (editorOwner)
        editorOwner.forceActiveFocus()
    } else if (bindingAction) {
      bindingAction = ""
      bindingDraft = ""
      if (editorOwner)
        editorOwner.forceActiveFocus()
    } else if (keyEditing) {
      keyEditing = false
      keyField.text = ""
      tokenButton.forceActiveFocus()
    } else
      close()
  }
  function requestDelete(item, owner, cancelControl) {
    deleteId = item.id
    deleteFilename = item.filename
    editorOwner = owner
    Qt.callLater(function () { if (cancelControl) cancelControl.forceActiveFocus() })
  }
  function audioError(raw) {
    try {
      var code = JSON.parse(String(raw).trim()).errorCode
      var key = "audio.error." + code
      var message = i18n.text(key)
      if (message !== key)
        return message
    } catch (e) {}
    return i18n.text("audio.error.io")
  }
  function refreshAudio() {
    if (audioListProc.running)
      audioRefreshQueued = true
    else {
      audioRefreshQueued = false
      audioListProc.running = true
    }
  }
  function audioAction(action, id) {
    if (audioActionProc.running)
      return
    error = ""
    audioMessage = ""
    if (action === "--audio-delete" && audioPreviewProc.running && audioPreviewProc.audioId === id)
      audioPreviewProc.stopping = true
    audioActionProc.command = [speakBin, action].concat(Array.isArray(id) ? id : id ? [id] : [])
    audioActionProc.running = true
  }
  function previewAudio(id) {
    if (audioPreviewProc.running || audioActionProc.running || busy)
      return
    error = ""
    audioPreviewProc.audioId = id
    audioPreviewProc.stopping = false
    audioPreviewProc.command = [speakBin, "--audio-preview", id]
    viewport.contentY = 0
    audioPreviewProc.running = true
  }
  function seekPreview(value) {
    if (!previewing || seekProc.running)
      return
    seekProc.command = [speakBin, "--playback-seek", String(Math.max(0, Math.min(previewDuration, value)))]
    seekProc.running = true
  }
  function audioTime(value) {
    var seconds = Math.max(0, Math.floor(value))
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0")
  }
  function createAudio() {
    if (busy || audioPreviewProc.running || speechProc.running || ocrBusy || audioActionProc.running)
      return
    error = ""
    audioMessage = ""
    exportMode = true
    if (["snip", "window", "screen"].indexOf(exportSource) >= 0) {
      readScreen(exportSource)
      return
    }
    if (exportSource === "sample") {
      pendingSpeech = sampleText
      speechProc.command = [speakBin, "--export-audio", "--format", exportFormat, "--stdin-json"]
      speechProc.running = true
    } else {
      audioAction("--export-audio", ["--format", exportFormat, "--" + exportSource])
    }
  }
  function pause() {
    if (!pauseProc.running) {
      error = ""
      pauseProc.running = true
    }
  }
  function changeRate(value, save) {
    rateOverride = value
    if (busy && playback.kind !== "export") {
      pendingRate = value
      if (save)
        sendRate()
      else if (!rateTimer.running)
        rateTimer.start()
    }
    if (save && !previewing)
      setConfig(".rate", value.toFixed(2))
  }
  function sendRate() {
    if (rateProc.running || pendingRate < 0)
      return
    rateProc.command = [speakBin, "--playback-rate", String(pendingRate)]
    pendingRate = -1
    rateProc.running = true
  }
  Connections {
    target: root.hostWidget
    function onLiveStateChanged() {
      if (!speedSlider.dragging && !rateProc.running && root.pendingRate < 0 && ((!root.busy && !configProc.running && root.queue.length === 0 && !root.infoBusy) || (root.busy && root.playback.playbackRate !== null && Math.abs(Number(root.playback.playbackRate) - root.rateOverride) < .02)))
        root.rateOverride = -1
      if (root.opened && root.panelPage === "audio" && root.lastAudioRevision !== String(root.playback.audioRevision)) {
        root.lastAudioRevision = String(root.playback.audioRevision)
        root.refreshAudio()
      }
    }
  }
  function updateLocalizedSample() {
    if (info.ui?.sampleIsDefault === true && !sampleDirty)
      sampleText = i18n.text("sample.text")
  }
  function beginBindingEdit(action, owner) {
    if (bindingBusy)
      return
    bindingAction = action.key
    editorOwner = owner || null
    bindingDraft = shortcutChord(action)
    chordField.text = bindingDraft
    bindingRecording = false
    Qt.callLater(function () {
      chordField.forceActiveFocus()
      root.reveal(chordField)
    })
  }
  function shortcutFromKey(event) {
    var key = ""
    if (event.key >= Qt.Key_A && event.key <= Qt.Key_Z)
      key = String.fromCharCode(event.key)
    else if (event.key >= Qt.Key_0 && event.key <= Qt.Key_9)
      key = String(event.key - Qt.Key_0)
    else if (event.key >= Qt.Key_F1 && event.key <= Qt.Key_F12)
      key = "F" + (event.key - Qt.Key_F1 + 1)
    else if (event.key === Qt.Key_Space)
      key = "SPACE"
    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
      key = "RETURN"
    else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab)
      key = "TAB"
    else if (event.key === Qt.Key_Backspace)
      key = "BACKSPACE"
    else if (event.key === Qt.Key_Left)
      key = "LEFT"
    else if (event.key === Qt.Key_Right)
      key = "RIGHT"
    else if (event.key === Qt.Key_Up)
      key = "UP"
    else if (event.key === Qt.Key_Down)
      key = "DOWN"
    else if (event.key === Qt.Key_Insert)
      key = "INSERT"
    else if (event.key === Qt.Key_Delete)
      key = "DELETE"
    if (!key)
      return ""
    var mods = []
    if (event.modifiers & Qt.MetaModifier)
      mods.push("SUPER")
    if (event.modifiers & Qt.ControlModifier)
      mods.push("CTRL")
    if (event.modifiers & Qt.AltModifier)
      mods.push("ALT")
    if (event.modifiers & Qt.ShiftModifier)
      mods.push("SHIFT")
    return mods.concat([key]).join(" + ")
  }
  function saveBinding() {
    if (bindingBusy || !bindingAction)
      return
    error = ""
    bindingBusy = true
    bindingWriteProc.command = [bindingsBin, "--locale", i18n.locale, "set", bindingAction, bindingDraft.trim()]
    bindingWriteProc.running = true
  }
  function installBindings() {
    if (bindingBusy)
      return
    error = ""
    bindingBusy = true
    bindingWriteProc.command = [bindingsBin, "--locale", i18n.locale, "install"]
    bindingWriteProc.running = true
  }
  function installedOcrLanguages() {
    return (info.ocr?.languages || []).filter(function (item) {
      return item.installed === true
    })
  }
  function ocrLanguageOptions() {
    var installed = installedOcrLanguages()
    var options = installed.map(function (item) {
      return {
        value: item.value,
        label: item.value === "rus" ? i18n.text("screen.language.ru") : item.value === "eng" ? i18n.text("screen.language.en") : item.label
      }
    })
    if (installed.some(function (item) {
      return item.value === "eng"
    }) && installed.some(function (item) {
      return item.value === "rus"
    }))
      options.unshift({
        value: "rus+eng",
        label: i18n.text("screen.language.both")
      })
    return options
  }
  function ocrStatusLabel() {
    if (info.ocr?.engine === "remote" && activeOcrEngine.status === "missing")
      return i18n.text("screen.status.notConfigured")
    var key = "screen.status." + String(activeOcrEngine.status || "untested")
    return i18n.text(key)
  }
  function remoteOcrStatusLabel() {
    var status = String(remoteOcrEngine.status || "untested")
    return i18n.text("screen.status." + (status === "missing" ? "notConfigured" : status))
  }
  function ocrEngineOptions() {
    var selected = String(info.ocr?.engine || "tesseract")
    return (info.ocr?.engines || []).filter(function (engine) {
      return engine.status === "ready" || engine.status === "untested" || engine.name === selected
    }).map(function (engine) {
      return {
        value: engine.name,
        label: i18n.text("screen.engineChoice", {
          name: engine.name === "remote" ? i18n.text("screen.remoteSource") : (engine.title || engine.name),
          status: i18n.text(engine.name === "remote" && engine.status === "missing" ? "screen.status.notConfigured" : "screen.status." + String(engine.status || "untested"))
        })
      }
    })
  }
  function ocrModelText() {
    if ((info.ocr?.engine || "tesseract") !== "tesseract")
      return ""
    return String(info.ocr?.langs || "eng").split("+").map(function (code) {
      return code + ".traineddata"
    }).join(" + ")
  }
  function missingOcrLanguages() {
    if ((info.ocr?.languages || []).length === 0)
      return []
    var installed = installedOcrLanguages().map(function (item) {
      return item.value
    })
    return String(info.ocr?.langs || "eng").split("+").filter(function (code) {
      return installed.indexOf(code) < 0
    })
  }

  function refresh() {
    if (infoBusy || infoProc.running || configProc.running || queue.length) {
      refreshQueued = true
      return
    }
    refreshQueued = false
    readEpoch = writeEpoch
    infoBusy = true
    infoProc.running = true
  }
  function setConfig(path, value) {
    error = ""
    if (infoProc.running || infoBusy)
      refreshQueued = true
    writeEpoch++
    if (path === ".teratts.voice")
      voiceBusy = true
    var next = queue.filter(function (item) {
      return item.path !== path
    })
    next.push({
      path: path,
      value: String(value)
    })
    queue = next
    refreshQueued = true
    runNextConfig()
  }
  function runNextConfig() {
    if (configProc.running || queue.length === 0)
      return
    var next = queue.slice()
    var item = next.shift()
    queue = next
    pendingValue = JSON.stringify(item.value)
    configProc.command = [speakBin, "--set-stdin-json", item.path]
    configProc.running = true
  }
  function readTextSource(source) {
    if (busy || speechProc.running || ["selection", "clipboard"].indexOf(source) < 0)
      return
    error = ""
    exportMode = false
    speechProc.command = [speakBin, "--" + source]
    speechProc.running = true
  }
  function speak(text) {
    error = ""
    if (speechProc.running)
      return
    pendingSpeech = String(text).slice(0, 4096)
    speechProc.command = [speakBin, "--stdin-json"]
    speechProc.running = true
  }
  function stop() {
    error = ""
    if (audioPreviewProc.running)
      audioPreviewProc.stopping = true
    if (!stopProc.running)
      stopProc.running = true
  }
  function readScreen(mode) {
    if (ocrBusy || ["snip", "window", "screen"].indexOf(mode) < 0)
      return
    error = ""
    ocrBusy = true
    requestedPage = exportMode ? "audio" : "read"
    root.close()
    ocrProc.command = [speakBin].concat(exportMode ? ["--export-audio", "--format", exportFormat] : [], ["--" + mode])
    ocrProc.running = true
  }
  function saveKey(key) {
    if (keyProc.running || !/^[\x21-\x7e]{8,4096}$/.test(key))
      return false
    error = ""
    keySaved = false
    pendingKey = key
    keyProc.running = true
    return true
  }

  onOpenedChanged: {
    if (opened) {
      selectPage(requestedPage)
      requestedPage = "read"
      if (panelPage === "audio")
        refreshAudio()
      refresh()
      bindingInfoLoaded = false
      bindingsInfoProc.running = true
    } else {
      keyEditing = false
      pendingKey = ""
      bindingRecording = false
      bindingAction = ""
      bindingDraft = ""
      deleteId = ""
    }
  }

  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: infoProc
    command: [root.speakBin, "--info"]
    stdout: StdioCollector {
      id: infoOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: infoErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (root.queue.length === 0 && !configProc.running)
        root.voiceBusy = false
      if (root.readEpoch !== root.writeEpoch)
        root.refreshQueued = true
      else if (code !== 0 || status !== 0)
        root.error = i18n.text("error.info")
      else {
        try {
          var result = JSON.parse(infoOut.text)
          if (result.provider !== "teratts" || !Array.isArray(result.voices))
            throw new Error("invalid response")
          root.info = result
          root.infoLoaded = true
          root.exportFormat = String(result.ui?.exportFormat || "mp3")
          root.rateOverride = -1
          root.voiceBusy = false
          if (!sampleField.activeFocus && !root.sampleDirty)
            root.sampleText = result.ui?.sampleIsDefault === true ? i18n.text("sample.text") : String(result.ui?.sampleText || root.sampleText)
        } catch (e) {
          root.error = i18n.text("error.infoParse")
        }
      }
    }
    onRunningChanged: if (!running) {
      root.infoBusy = false
      if (root.refreshQueued && !configProc.running && root.queue.length === 0)
        Qt.callLater(function () {
          if (root.refreshQueued)
            root.refresh()
        })
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: configProc
    command: []
    stdinEnabled: true
    onStarted: {
      write(root.pendingValue + "\n")
      root.pendingValue = ""
    }
    stderr: StdioCollector {
      id: configErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0) {
        root.error = i18n.text("error.config")
        root.voiceBusy = false
      }
    }
    onRunningChanged: if (!running) {
      if (root.queue.length)
        Qt.callLater(root.runNextConfig)
      else
        root.refresh()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: speechProc
    command: []
    stdinEnabled: true
    onStarted: {
      if (command.indexOf("--stdin-json") >= 0)
        write(JSON.stringify(root.pendingSpeech) + "\n")
      root.pendingSpeech = ""
    }
    stderr: StdioCollector {
      id: speechErr
      waitForEnd: true
    }
    stdout: StdioCollector {
      id: speechOut
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = root.audioError(speechErr.text)
      else if (root.exportMode && speechOut.text.trim())
        root.audioMessage = i18n.text("audio.ready")
      root.exportMode = false
      if (root.panelPage === "audio")
        root.refreshAudio()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: stopProc
    command: [root.speakBin, "--stop"]
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: pauseProc
    command: [root.speakBin, "--pause-toggle"]
    stderr: StdioCollector {
      id: pauseErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = root.audioError(pauseErr.text)
    }
  }
  Timer {
    id: rateTimer
    interval: 100
    onTriggered: root.sendRate()
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: rateProc
    command: []
    stderr: StdioCollector {
      id: rateErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0) {
        root.error = root.audioError(rateErr.text)
        root.rateOverride = -1
      }
    }
    onRunningChanged: if (!running && root.pendingRate >= 0)
      rateTimer.restart()
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: seekProc
    command: []
    stderr: StdioCollector {
      id: seekErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = root.audioError(seekErr.text)
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: audioListProc
    command: [root.speakBin, "--audio-list"]
    stdout: StdioCollector {
      id: audioListOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: audioListErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0) {
        root.error = root.audioError(audioListErr.text)
        return
      }
      try {
        var items = JSON.parse(audioListOut.text)
        if (Array.isArray(items) && items.length <= 128)
          root.audioItems = items
      } catch (e) {
        root.error = i18n.text("audio.error.io")
      }
    }
    onRunningChanged: if (!running && root.audioRefreshQueued)
      Qt.callLater(root.refreshAudio)
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: audioPreviewProc
    property string audioId: ""
    property bool stopping: false
    command: []
    stderr: StdioCollector {
      id: audioPreviewErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if ((code !== 0 || status !== 0) && !stopping)
        root.error = root.audioError(audioPreviewErr.text)
      root.refreshAudio()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: audioActionProc
    command: []
    stdout: StdioCollector {
      id: audioActionOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: audioActionErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (command[1] === "--export-audio")
        root.exportMode = false
      if (code !== 0 || status !== 0) {
        root.error = root.audioError(audioActionErr.text)
        if (command[1] === "--audio-delete")
          audioPreviewProc.stopping = false
      } else if (command[1] === "--audio-copy")
        root.audioMessage = i18n.text("audio.copied")
      else if (command[1] === "--export-audio" && audioActionOut.text.trim())
        root.audioMessage = i18n.text("audio.ready")
      root.refreshAudio()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: bindingsInfoProc
    command: [root.bindingsBin, "status"]
    stdout: StdioCollector {
      id: bindingsOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: bindingsErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0) {
        root.error = i18n.text("error.bindings")
        return
      }
      try {
        var result = JSON.parse(bindingsOut.text)
        if (!result.bindings || !Array.isArray(result.conflicts))
          throw new Error("invalid bindings")
        root.bindingInfo = result
        root.bindingInfoLoaded = true
      } catch (e) {
        root.error = i18n.text("error.bindings")
      }
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: bindingWriteProc
    command: []
    stderr: StdioCollector {
      id: bindingWriteErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = i18n.text("error.bindingSave")
      else {
        root.bindingAction = ""
        root.bindingInfoLoaded = false
        bindingsInfoProc.running = false
        bindingsInfoProc.running = true
      }
    }
    onRunningChanged: if (!running)
      root.bindingBusy = false
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: languagesProc
    command: [root.speakBin, "--refresh-languages", "tesseract"]
    stderr: StdioCollector {
      id: languagesErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = i18n.text("error.languages")
      else
        root.refresh()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: ocrVerifyProc
    command: [root.speakBin, "--verify-ocr", root.info.ocr?.engine || "tesseract"]
    stderr: StdioCollector {
      id: ocrVerifyErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = i18n.text("error.verifyOcr")
      root.refresh()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: ocrServerVerifyProc
    command: [root.speakBin, "--verify-ocr", "remote"]
    stderr: StdioCollector {
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = i18n.text("error.verifyOcr")
      root.refresh()
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale, TTS_CAPTURE_DELAY: "0.25"})
    id: ocrProc
    command: []
    stdout: StdioCollector {
      id: ocrOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: ocrErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = root.exportMode ? root.audioError(ocrErr.text) : i18n.text("error.screen")
      else if (root.exportMode && String(ocrOut.text).trim()) {
        try {
          var result = JSON.parse(ocrOut.text)
          if (!result.id || !result.filename)
            throw new Error("invalid export result")
          root.audioMessage = i18n.text("audio.ready")
        } catch (e) {
          root.error = i18n.text("audio.error.io")
        }
      }
      root.exportMode = false
      root.refreshAudio()
    }
    onRunningChanged: if (!running)
      root.ocrBusy = false
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: keyProc
    command: [root.setupBin, "key-store", "teratts"]
    stdinEnabled: true
    onStarted: {
      write(root.pendingKey + "\n")
      root.pendingKey = ""
    }
    stdout: StdioCollector {
      id: keyOut
      waitForEnd: true
    }
    onExited: function (code, status) {
      try {
        var result = JSON.parse(keyOut.text)
        if (code !== 0 || status !== 0 || result.ok !== true)
          root.error = i18n.text("error.token")
        else {
          root.keySaved = true
          root.keyEditing = false
          root.refresh()
        }
      } catch (e) {
        root.error = i18n.text("error.token")
      }
    }
  }
  Process {
    environment: ({TTS_UI_LOCALE: i18n.locale})
    id: voicesProc
    command: [root.speakBin, "--refresh-voices", "teratts"]
    stderr: StdioCollector {
      id: voicesErr
      waitForEnd: true
    }
    onExited: function (code, status) {
      if (code !== 0 || status !== 0)
        root.error = i18n.text("error.voices")
      root.refresh()
    }
  }

  component CopyLabel: Text {
    textFormat: Text.PlainText
    color: Host.Color.popups.text
    font.family: root.ff
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }
  component CopyNote: CopyLabel {
    font.pixelSize: Style.font.bodySmall
    color: Qt.darker(Host.Color.popups.text, 1.15)
  }
  component PanelHeading: Item {
    id: heading
    property string text: ""
    property string iconText: ""
    property real fontSize: Style.font.caption
    width: parent ? parent.width : implicitWidth
    implicitWidth: sectionGlyph.width + Style.spacing.controlGap + sectionLabel.implicitWidth
    implicitHeight: Math.max(sectionGlyph.implicitHeight, sectionLabel.implicitHeight)
    Text {
      id: sectionGlyph
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: heading.iconText
      color: sectionLabel.color
      font.family: root.ff
      font.pixelSize: Style.font.icon
      Accessible.ignored: true
    }
    PanelSectionHeader {
      id: sectionLabel
      anchors.left: sectionGlyph.right
      anchors.leftMargin: Style.spacing.controlGap
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: heading.text
      foreground: Host.Color.popups.text
      fontFamily: root.ff
      fontSize: heading.fontSize
      wrapMode: Text.WordWrap
    }
  }
  component PanelAction: Button {
    foreground: Host.Color.popups.text
    fontFamily: root.ff
    focusable: true
    bordered: true
    opacity: enabled ? 1 : .45
    Accessible.role: Accessible.Button
    Accessible.name: text
  }

  Connections {
    target: content.Window.window
    function onActiveFocusItemChanged() {
      var item = content.Window.window.activeFocusItem
      if (item)
        Qt.callLater(function() { root.reveal(item) })
    }
  }

  KeyboardPanel {
    id: panelCard
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: content
    contentWidth: fittedContentWidth(Style.space(380))
    contentHeight: cappedContentHeight(Style.space(540))

    Item {
      id: content
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.cancelEditor()

      Column {
        id: header
        width: parent.width
        spacing: Style.spacing.controlGap
        Row {
          id: panelIdentity
          width: parent.width
          spacing: Style.spacing.panelGap
          TeraIcon {
            id: panelIcon
            iconSize: Style.font.display
            color: Host.Color.popups.text
            playing: root.speaking
            levels: root.playback.bands || [0, 0, 0, 0]
            busy: ["preparing", "buffering", "exporting"].indexOf(root.playback.status) >= 0
            anchors.verticalCenter: parent.verticalCenter
          }
          Column {
            width: parent.width - panelIcon.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            CopyLabel {
              width: parent.width
              text: "TeraTTS"
              font.pixelSize: Style.font.heading
              font.bold: true
            }
            CopyNote {
              id: stateLabel
              width: parent.width
              text: root.infoBusy && !root.infoLoaded ? i18n.text("hero.loading")
                : i18n.text("state." + (root.paused ? "paused" : root.playback.status || "idle"))
              font.pixelSize: Style.font.caption
              wrapMode: Text.NoWrap
              elide: Text.ElideRight
            }
          }
        }
        Row {
          id: pageTabs
          width: parent.width
          spacing: Style.space(3)
          Repeater {
            model: [{key:"read",label:"nav.read"}, {key:"audio",label:"nav.files"}, {key:"settings",label:"nav.settings"}]
            delegate: PanelAction {
              required property var modelData
              width: (pageTabs.width - pageTabs.spacing * 2) / 3
              height: Style.space(32)
              text: i18n.text(modelData.label)
              iconText: root.glyphs[modelData.key]
              iconSize: Style.font.iconSmall
              horizontalPadding: Style.space(4)
              bordered: false
              selected: root.panelPage === modelData.key
              onClicked: root.selectPage(modelData.key)
            }
          }
        }
        PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
      }

      Column {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width
        spacing: Style.space(6)
        PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
        Row {
          id: playbackControls
          width: parent.width
          spacing: Style.spacing.controlGap
          PanelAction {
            id: pauseButton
            width: (parent.width - parent.spacing) / 2
            height: Style.space(34)
            text: i18n.text(root.paused ? "action.resume" : "action.pause")
            iconText: root.paused ? root.glyphs.play : root.glyphs.pause
            enabled: root.busy && root.playback.kind !== "export" && !pauseProc.running
            onClicked: root.pause()
          }
          PanelAction {
            id: stopButton
            width: (parent.width - parent.spacing) / 2
            height: Style.space(34)
            text: i18n.text("action.stop")
            iconText: root.glyphs.stop
            tooltipText: i18n.text("control.stopHint")
            enabled: !stopProc.running
            onClicked: root.stop()
          }
        }
        CopyNote {
          objectName: "cancelHint"
          width: parent.width
          height: Math.ceil(font.pixelSize * 2.6)
          text: root.effectiveStopChord ? i18n.text("control.stopShortcut", {chord:root.effectiveStopChord})
            : i18n.text("control.stopUnassigned")
        }
      }

      Flickable {
        id: viewport
        anchors.top: header.bottom
        anchors.topMargin: Style.spacing.controlGap
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: footer.top
        anchors.bottomMargin: Style.spacing.controlGap
        anchors.rightMargin: scrollBar.visible ? Style.spacing.controlGap : 0
        contentWidth: width
        contentHeight: form.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        onContentHeightChanged: focusReveal.restart()
        Timer {
          id: focusReveal
          interval: 0
          onTriggered: {
            var window = content.Window.window
            if (window && window.activeFocusItem)
              root.reveal(window.activeFocusItem)
          }
        }
        ScrollBar.vertical: ScrollBar {
          id: scrollBar
          parent: content
          anchors.top: viewport.top
          anchors.bottom: viewport.bottom
          anchors.right: parent.right
          width: Style.space(3)
          policy: ScrollBar.AsNeeded
          contentItem: Rectangle {
            implicitWidth: Style.space(3)
            radius: width / 2
            color: Host.Color.popups.text
            opacity: scrollBar.active || scrollBar.hovered ? .65 : .3
          }
        }
        Column {
          id: form
          // Keep native border strokes inside the viewport's clip at fractional scale.
          x: Style.spacing.xxs
          width: Math.max(0, viewport.width - x * 2)
          spacing: Style.spacing.panelGap
          CopyLabel {
            id: errorMessage
            width: parent.width
            visible: root.error !== "" || root.playback.status === "error"
            text: root.error || i18n.text("audio.error." + (root.playback.errorCode || "io"))
            font.pixelSize: Style.font.bodySmall
          }

          Column {
            id: previewPlayer
            width: parent.width
            visible: root.previewing
            enabled: visible
            spacing: Style.space(6)
            CopyLabel {
              width: parent.width
              text: root.previewItem.filename || i18n.text("audio.playingFile")
              wrapMode: Text.NoWrap
              elide: Text.ElideMiddle
              font.bold: true
            }
            PanelSlider {
              id: audioSeekSlider
              width: parent.width
              bar: root.bar
              trackColor: Style.selectedFillFor(Host.Color.popups.text, Host.Color.accent)
              fillColor: Host.Color.popups.text
              knobColor: Host.Color.popups.text
              activeFocusOnTab: true
              enabled: root.previewDuration > 0 && ["playing", "paused"].indexOf(root.playback.status) >= 0 && !seekProc.running
              minimum: 0
              maximum: Math.max(.01, root.previewDuration)
              step: 5
              value: root.previewPosition
              onReleased: function(v) { root.seekPreview(v) }
              Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Left) root.seekPreview(Math.max(0, root.previewPosition - 5))
                else if (event.key === Qt.Key_Right) root.seekPreview(Math.min(root.previewDuration, root.previewPosition + 5))
                else if (event.key === Qt.Key_Home) root.seekPreview(0)
                else if (event.key === Qt.Key_End) root.seekPreview(root.previewDuration)
                else return
                event.accepted = true
              }
              Rectangle {
                anchors.fill: parent
                visible: audioSeekSlider.activeFocus
                color: "transparent"
                radius: Style.cornerRadius
                border.width: Style.normalBorderWidth
                border.color: Host.Color.popups.text
              }
              Accessible.name: i18n.text("audio.player")
            }
            CopyNote {
              text: i18n.text("audio.progress", {elapsed:root.audioTime(audioSeekSlider.dragging ? audioSeekSlider.liveValue : root.previewPosition), total:root.audioTime(root.previewDuration)})
            }
            PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
          }

          Column {
            id: readPage
            width: parent.width
            visible: root.panelPage === "read"
            enabled: visible
            spacing: Style.spacing.panelGap
            Column {
              width: parent.width
              spacing: Style.spacing.controlGap
              PanelHeading { text: i18n.text("read.text"); iconText: root.glyphs.read }
              Row {
                width: parent.width
                spacing: Style.spacing.controlGap
                PanelAction {
                  id: selectionButton
                  width: (parent.width - parent.spacing) / 2
                  height: Style.space(42)
                  text: i18n.text("read.selection")
                  iconText: root.glyphs.selection
                  background: Style.selectedFillFor(Host.Color.popups.text, Host.Color.accent)
                  tooltipText: root.shortcutChord(root.bindingActions[0])
                  enabled: root.infoLoaded && !root.busy && !speechProc.running
                  onClicked: root.readTextSource("selection")
                }
                PanelAction {
                  id: clipboardButton
                  width: (parent.width - parent.spacing) / 2
                  height: Style.space(42)
                  text: i18n.text("read.clipboard")
                  iconText: root.glyphs.clipboard
                  tooltipText: root.shortcutChord(root.bindingActions[1])
                  enabled: root.infoLoaded && !root.busy && !speechProc.running
                  onClicked: root.readTextSource("clipboard")
                }
              }
            }
            Column {
              width: parent.width
              spacing: Style.space(6)
              PanelHeading { text: i18n.text("read.screen"); iconText: root.glyphs.screen }
              Row {
                width: parent.width
                spacing: Style.spacing.controlGap
                Repeater {
                  model: [{mode:"snip",label:"screen.area"}, {mode:"window",label:"screen.window"}, {mode:"screen",label:"screen.monitor"}]
                  delegate: PanelAction {
                    required property var modelData
                    width: (parent.width - parent.spacing * 2) / 3
                    height: Style.space(32)
                    text: i18n.text(modelData.label)
                    iconText: root.glyphs[modelData.mode]
                    iconSize: Style.font.iconSmall
                    horizontalPadding: Style.space(4)
                    enabled: root.infoLoaded && !root.busy && !root.ocrBusy
                    onClicked: root.readScreen(modelData.mode)
                  }
                }
              }
              PanelAction {
                id: ocrSettingsButton
                width: parent.width
                text: i18n.text("read.ocr", {name:root.ocrName(),status:root.ocrStatusLabel()})
                iconText: root.glyphs.ocr
                iconSize: Style.font.iconSmall
                fontSize: Style.font.bodySmall
                bordered: false
                leftAlign: true
                horizontalPadding: 0
                verticalPadding: Style.space(2)
                tooltipText: i18n.text("read.ocrSettings")
                onClicked: root.selectSettings("screen")
              }
            }
            PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
            Column {
              width: parent.width
              spacing: Style.spacing.controlGap
              Row {
                width: parent.width
                spacing: Style.spacing.controlGap
                PanelHeading { text: i18n.text("voice.section"); iconText: root.glyphs.voice; width: parent.width - refreshButton.width - parent.spacing }
                PanelAction {
                  id: refreshButton
                  text: voicesProc.running ? i18n.text("action.refreshing") : i18n.text("action.refresh")
                  iconText: root.glyphs.refresh
                  iconSize: Style.font.iconSmall
                  bordered: false
                  fontSize: Style.font.bodySmall
                  verticalPadding: 0
                  enabled: !voicesProc.running
                  onClicked: voicesProc.running = true
                }
              }
              Dropdown {
                id: voiceDropdown
                width: parent.width
                showLabel: false
                foreground: Host.Color.popups.text
                fontFamily: root.ff
                enabled: root.infoLoaded && !root.voiceBusy && (root.info.voices || []).length > 0
                options: root.voiceOptions()
                value: root.info.voice || "ru_f1"
                onChanged: function(value) { if (value && value !== root.info.voice) root.setConfig(".teratts.voice", value) }
              }
              CopyNote { width: parent.width; visible: root.infoLoaded && (root.info.voices || []).length === 0; text: i18n.text("voice.empty") }

            }
          }

          Column {
            id: rateControl
            width: parent.width
            visible: root.panelPage === "read" || root.busy && root.playback.kind !== "export"
            enabled: visible
            spacing: Style.spacing.controlGap
              Row {
                width: parent.width
                PanelHeading { text: i18n.text(root.previewing ? "audio.previewSpeed" : "voice.speed"); iconText: root.glyphs.speed; width: parent.width - rateText.width }
                CopyLabel { id: rateText; text: root.rateValue.toFixed(2) + "×" }
              }
              Row {
                width: parent.width
                spacing: Style.spacing.controlGap
                PanelAction {
                  id: slowerButton
                  width: Style.space(30)
                  height: Style.space(30)
                  text: "−"
                  enabled: root.infoLoaded
                  Accessible.name: i18n.text("control.slower")
                  onClicked: root.changeRate(Math.max(.25, Math.round((root.rateValue - .1) * 20) / 20), true)
                }
                PanelSlider {
                  id: speedSlider
                  width: parent.width - slowerButton.width - fasterButton.width - parent.spacing * 2
                  height: slowerButton.height
                  bar: root.bar
                  trackColor: Style.selectedFillFor(Host.Color.popups.text, Host.Color.accent)
                  fillColor: Host.Color.popups.text
                  knobColor: Host.Color.popups.text
                  activeFocusOnTab: true
                  enabled: root.infoLoaded
                  minimum: .25
                  maximum: 4
                  step: .05
                  value: root.rateValue
                  onMoved: function(v) { var s = Math.round(v * 20) / 20; speedSlider.liveValue = s; root.changeRate(s, false) }
                  onReleased: function(v) { root.changeRate(Math.round(v * 20) / 20, true) }
                  Keys.onPressed: function(event) {
                    var value = root.rateValue
                    if (event.key === Qt.Key_Left) value -= .05
                    else if (event.key === Qt.Key_Right) value += .05
                    else if (event.key === Qt.Key_Home) value = .25
                    else if (event.key === Qt.Key_End) value = 4
                    else return
                    root.changeRate(Math.max(.25, Math.min(4, Math.round(value * 20) / 20)), true)
                    event.accepted = true
                  }
                  Rectangle {
                    anchors.fill: parent
                    visible: speedSlider.activeFocus
                    color: "transparent"
                    radius: Style.cornerRadius
                    border.width: Style.normalBorderWidth
                    border.color: Host.Color.popups.text
                  }
                  Accessible.name: i18n.text("voice.speed")
                }
                PanelAction {
                  id: fasterButton
                  width: Style.space(30)
                  height: Style.space(30)
                  text: "+"
                  enabled: root.infoLoaded
                  Accessible.name: i18n.text("control.faster")
                  onClicked: root.changeRate(Math.min(4, Math.round((root.rateValue + .1) * 20) / 20), true)
                }
              }
          }

          Column {
            id: audioPage
            width: parent.width
            visible: root.panelPage === "audio"
            enabled: visible
            spacing: Style.spacing.controlGap
            Row {
              width: parent.width
              spacing: Style.spacing.controlGap
              PanelHeading { text: i18n.text("audio.files"); iconText: root.glyphs.audio; width: parent.width - createToggle.width - parent.spacing }
              PanelAction {
                id: createToggle
                text: i18n.text(root.audioCreateOpen ? "audio.hideCreate" : "audio.create")
                iconText: root.audioCreateOpen ? root.glyphs.cancel : root.glyphs.export
                iconSize: Style.font.iconSmall
                horizontalPadding: Style.space(4)
                bordered: false
                selected: root.audioCreateOpen
                onClicked: root.audioCreateOpen = !root.audioCreateOpen
              }
            }
            Column {
              id: audioCreateForm
              width: parent.width
              visible: root.audioCreateOpen
              enabled: visible
              spacing: Style.spacing.controlGap
              Dropdown {
                id: exportSourceDropdown
                width: parent.width
                showLabel: false
                foreground: Host.Color.popups.text
                fontFamily: root.ff
                value: root.exportSource
                options: ["selection", "clipboard", "snip", "window", "screen", "sample"].map(function(source) { return {value:source, label:i18n.text("audio.source." + source)} })
                onChanged: function(value) { root.exportSource = value }
              }
              Row {
                width: parent.width
                spacing: Style.spacing.controlGap
                Dropdown {
                  id: exportFormatDropdown
                  width: (parent.width - parent.spacing) * .45
                  showLabel: false
                  foreground: Host.Color.popups.text
                  fontFamily: root.ff
                  value: root.exportFormat
                  options: ["mp3", "ogg", "wav"].map(function(format) { return {value:format, label:format === "ogg" ? "OGG / Opus" : format.toUpperCase()} })
                  onChanged: function(value) { root.exportFormat = value; root.setConfig(".ui.exportFormat", value) }
                }
                PanelAction {
                  id: createAudioButton
                  width: parent.width - exportFormatDropdown.width - parent.spacing
                  text: i18n.text("audio.createFile")
                  iconText: root.glyphs.export
                  horizontalPadding: Style.space(4)
                  enabled: root.infoLoaded && !root.busy && !root.ocrBusy && !audioPreviewProc.running && !audioActionProc.running && !speechProc.running
                  onClicked: root.createAudio()
                }
              }
              CopyNote { width: parent.width; text: i18n.text("audio.exportHint") }
              PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
            }
            CopyNote { width: parent.width; visible: root.audioMessage !== ""; text: root.audioMessage }
            CopyLabel { width: parent.width; visible: root.audioItems.length === 0; text: i18n.text(audioListProc.running ? "audio.loading" : "audio.empty") }
            Repeater {
              id: audioRows
              model: root.audioItems
              delegate: Column {
                id: audioRow
                required property var modelData
                readonly property bool activePreview: root.previewing && root.playback.audioId === modelData.id
                width: parent.width
                spacing: Style.space(5)
                CopyLabel { width: parent.width; text: root.audioTitle(audioRow.modelData); font.bold: true; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                CopyNote { width: parent.width; text: audioRow.modelData.filename; wrapMode: Text.NoWrap; elide: Text.ElideMiddle }
                Grid {
                  width: parent.width
                  columns: width >= Style.space(320) ? 3 : 1
                  spacing: Style.space(4)
                  PanelAction {
                    width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
                    text: i18n.text(audioRow.activePreview ? root.paused ? "action.resume" : "action.pause" : "audio.preview")
                    iconText: audioRow.activePreview && !root.paused ? root.glyphs.pause : root.glyphs.play
                    iconSize: Style.font.iconSmall
                    horizontalPadding: Style.space(4)
                    leftAlign: parent.columns === 1
                    fontSize: Style.font.bodySmall
                    enabled: audioRow.activePreview ? !pauseProc.running : !audioPreviewProc.running && !root.busy && !audioActionProc.running
                    onClicked: audioRow.activePreview ? root.pause() : root.previewAudio(audioRow.modelData.id)
                  }
                  PanelAction {
                    width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
                    text: i18n.text("audio.copy")
                    iconText: root.glyphs.copy
                    iconSize: Style.font.iconSmall
                    horizontalPadding: Style.space(4)
                    leftAlign: parent.columns === 1
                    fontSize: Style.font.bodySmall
                    enabled: !audioActionProc.running
                    onClicked: root.audioAction("--audio-copy", audioRow.modelData.id)
                  }
                  PanelAction {
                    id: rowDeleteButton
                    width: (parent.width - parent.spacing * (parent.columns - 1)) / parent.columns
                    text: i18n.text("audio.delete")
                    iconText: root.glyphs.remove
                    iconSize: Style.font.iconSmall
                    horizontalPadding: Style.space(4)
                    leftAlign: parent.columns === 1
                    fontSize: Style.font.bodySmall
                    enabled: !audioActionProc.running
                    onClicked: root.requestDelete(audioRow.modelData, rowDeleteButton, deleteCancel)
                  }
                }
                Column {
                  width: parent.width
                  visible: root.deleteId === audioRow.modelData.id
                  enabled: visible
                  spacing: Style.space(5)
                  CopyLabel { width: parent.width; text: i18n.text("audio.deleteConfirm", {filename:root.deleteFilename}); wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.bodySmall }
                  Row {
                    width: parent.width
                    spacing: Style.spacing.controlGap
                    PanelAction {
                      width: (parent.width - parent.spacing) / 2
                      text: i18n.text("audio.delete")
                      iconText: root.glyphs.remove
                      enabled: !audioActionProc.running
                      onClicked: { var id = root.deleteId; root.deleteId = ""; root.audioAction("--audio-delete", id) }
                    }
                    PanelAction {
                      id: deleteCancel
                      width: (parent.width - parent.spacing) / 2
                      text: i18n.text("action.cancel")
                      iconText: root.glyphs.cancel
                      onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(deleteCancel) })
                      onClicked: root.cancelEditor()
                    }
                  }
                }
                PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
              }
            }
            PanelAction { width: parent.width; text: i18n.text("audio.openFolder"); iconText: root.glyphs.folder; bordered: false; enabled: !audioActionProc.running; onClicked: root.audioAction("--audio-open-folder", "") }
          }

          Column {
            id: settingsView
            width: parent.width
            visible: root.panelPage === "settings"
            enabled: visible
            spacing: Style.spacing.panelGap
            Grid {
              id: settingsTabs
              width: parent.width
              columns: width >= Style.space(320) ? 4 : 2
              spacing: Style.space(2)
              Repeater {
                model: [{key:"voice",label:"tab.voice"},{key:"screen",label:"nav.ocr"},{key:"server",label:"tab.server"},{key:"keys",label:"tab.keys"}]
                delegate: PanelAction {
                  required property var modelData
                  width: (settingsTabs.width - settingsTabs.spacing * (settingsTabs.columns - 1)) / settingsTabs.columns
                  text: i18n.text(modelData.label)
                  iconText: root.glyphs[modelData.key === "screen" ? "ocr" : modelData.key]
                  iconSize: Style.font.iconSmall
                  horizontalPadding: Style.space(4)
                  fontSize: Style.font.bodySmall
                  bordered: false
                  selected: root.settingsPage === modelData.key
                  onClicked: root.selectSettings(modelData.key)
                }
              }
            }
            Column {
              width: parent.width
              visible: root.settingsPage === "voice"
              enabled: visible
              spacing: Style.spacing.controlGap
              PanelHeading { text: i18n.text("voice.sample"); iconText: root.glyphs.voice }
              CopyNote { width: parent.width; text: i18n.text("voice.testHint", {voice:root.info.voice || "ru_f1"}) }
              TextField {
                id: sampleField
                width: parent.width
                text: root.sampleText
                maximumLength: 4096
                foreground: Host.Color.popups.text
                selectByMouse: true
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(sampleField) })
                onTextChanged: { root.sampleText = text; if (activeFocus) root.sampleDirty = true }
                onEditingFinished: if (root.sampleDirty) { root.setConfig(".ui.sampleText", text); root.sampleDirty = false }
                onAccepted: if (!root.busy && root.sampleText) root.speak(root.sampleText)
              }
              PanelAction {
                id: testButton
                text: i18n.text("voice.test")
                iconText: root.glyphs.play
                enabled: root.infoLoaded && !root.busy && !speechProc.running && root.sampleText.length > 0
                onClicked: root.speak(root.sampleText)
              }
              CopyNote { width: parent.width; text: i18n.text("voice.settingsHint") }
            }
            Column {
              width: parent.width
              visible: root.settingsPage === "screen"
              enabled: visible
              spacing: Style.spacing.controlGap
              PanelHeading { text: i18n.text("screen.sourceSection"); iconText: root.glyphs.ocr }
              Dropdown {
                id: ocrEngineDropdown
                width: parent.width
                showLabel: false
                foreground: Host.Color.popups.text
                fontFamily: root.ff
                enabled: root.infoLoaded && root.ocrEngineOptions().length > 0
                options: root.ocrEngineOptions()
                value: root.info.ocr?.engine || "tesseract"
                onChanged: function(value) { if (value && value !== root.info.ocr?.engine) root.setConfig(".ocr.engine", value) }
              }
              CopyNote { width: parent.width; text: i18n.text("screen.status", {status:root.ocrStatusLabel(), location:i18n.text(root.activeOcrEngine.kind === "remote" ? "screen.remote" : root.activeOcrEngine.kind === "cloud" ? "screen.cloud" : "screen.local")}) }
              CopyLabel { width: parent.width; visible: root.infoLoaded && root.ocrEngineOptions().length === 0; text: i18n.text("screen.noEngine") }
              CopyNote { width: parent.width; visible: root.ocrModelText() !== ""; text: i18n.text("screen.model", {model:root.ocrModelText()}) }
              CopyNote { width: parent.width; visible: root.activeOcrEngine.kind === "cloud" && !!root.info.ocr?.model; text: i18n.text("screen.cloudModel", {model:root.info.ocr?.model || ""}) }
              CopyNote { width: parent.width; visible: root.info.ocr?.engine === "easyocr"; text: i18n.text("screen.languages", {languages:root.info.ocr?.langs || "eng"}) }
              CopyNote { width: parent.width; visible: root.activeOcrEngine.kind === "remote"; text: i18n.text("screen.remoteModelManaged") }
              CopyNote { width: parent.width; visible: root.activeOcrEngine.kind === "cloud" || root.activeOcrEngine.kind === "remote"; text: i18n.text(root.activeOcrEngine.kind === "remote" ? "screen.remoteWarning" : "screen.cloudWarning") }
              Column {
                width: parent.width
                visible: (root.info.ocr?.engine || "tesseract") === "tesseract"
                enabled: visible
                spacing: Style.spacing.controlGap
                PanelHeading { text: i18n.text("screen.languageSection"); iconText: root.glyphs.language }
                Dropdown {
                  id: ocrLanguageDropdown
                  width: parent.width
                  showLabel: false
                  foreground: Host.Color.popups.text
                  fontFamily: root.ff
                  enabled: root.infoLoaded && root.ocrLanguageOptions().length > 0
                  options: root.ocrLanguageOptions()
                  value: root.info.ocr?.langs || "eng"
                  onChanged: function(value) { if (value && value !== root.info.ocr?.langs) root.setConfig(".ocr.tesseract.langs", value) }
                }
                CopyNote { width: parent.width; visible: (root.info.ocr?.languages || []).length === 0; text: i18n.text("screen.languagesEmpty") }
                CopyLabel { width: parent.width; visible: root.missingOcrLanguages().length > 0; text: i18n.text("screen.languageMissing", {languages:root.missingOcrLanguages().join(", ")}) }
                CopyNote { width: parent.width; visible: (root.info.ocr?.languages || []).length > 0 && !root.installedOcrLanguages().some(function(item) { return item.value === "rus" }); text: i18n.text("screen.russianMissing") }
                PanelAction { text: languagesProc.running ? i18n.text("action.refreshing") : i18n.text("screen.refreshLanguages"); iconText: root.glyphs.refresh; enabled: !languagesProc.running; onClicked: languagesProc.running = true }
              }
              PanelAction {
                text: ocrVerifyProc.running ? i18n.text("action.checking") : i18n.text("screen.verifyOcr")
                iconText: root.glyphs.check
                enabled: root.infoLoaded && !ocrVerifyProc.running && root.activeOcrEngine.status !== "missing" && root.activeOcrEngine.status !== "nokey"
                onClicked: { root.error = ""; ocrVerifyProc.running = true }
              }
            }
            Column {
              width: parent.width
              visible: root.settingsPage === "server"
              enabled: visible
              spacing: Style.spacing.controlGap
              PanelHeading { text: i18n.text("server.address"); iconText: root.glyphs.server }
              TextField {
                id: endpointField
                width: parent.width
                foreground: Host.Color.popups.text
                text: root.info.endpoint || ""
                placeholderText: "https://tts.example.com"
                selectByMouse: true
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(endpointField) })
                onEditingFinished: if (root.infoLoaded && text !== root.info.endpoint) root.setConfig(".teratts.endpoint", text)
              }
              CopyNote { width: parent.width; text: i18n.text("server.addressHint") }
              PanelAction {
                id: tokenButton
                text: i18n.text(root.keyEditing ? "server.hideToken" : "server.showToken")
                iconText: root.glyphs.key
                onClicked: root.keyEditing = !root.keyEditing
              }
              Column {
                width: parent.width
                visible: root.keyEditing
                enabled: visible
                spacing: Style.space(5)
                TextField {
                  id: keyField
                  width: parent.width
                  password: true
                  maximumLength: 4096
                  foreground: Host.Color.popups.text
                  placeholderText: i18n.text("server.tokenPlaceholder")
                  selectByMouse: true
                  onVisibleChanged: if (!visible) text = ""
                  onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(keyField) })
                  onAccepted: if (root.saveKey(text)) text = ""
                }
                PanelAction {
                  id: keyButton
                  text: i18n.text("action.save")
                  iconText: root.glyphs.save
                  enabled: !keyProc.running && /^[\x21-\x7e]{8,4096}$/.test(keyField.text)
                  onClicked: if (root.saveKey(keyField.text)) keyField.text = ""
                }
              }
              CopyNote { width: parent.width; text: i18n.text(root.keySaved ? "server.tokenSaved" : "server.tokenHint") }
              PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
              PanelHeading { text: i18n.text("server.ocrAddress"); iconText: root.glyphs.server }
              TextField {
                id: ocrEndpointField
                width: parent.width
                foreground: Host.Color.popups.text
                text: root.info.ocr?.remoteEndpoint || ""
                placeholderText: i18n.text("server.ocrAddressPlaceholder")
                selectByMouse: true
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(ocrEndpointField) })
                onEditingFinished: if (root.infoLoaded && text !== root.info.ocr?.remoteEndpoint) root.setConfig(".ocr.remote.endpoint", text)
              }
              CopyNote { width: parent.width; text: i18n.text("server.ocrAddressHint") }
              PanelAction {
                text: ocrServerVerifyProc.running ? i18n.text("action.checking") : i18n.text("server.verifyOcr")
                iconText: root.glyphs.check
                enabled: root.infoLoaded && !ocrServerVerifyProc.running && !configProc.running && root.queue.length === 0 && !!root.info.ocr?.remoteEndpoint && ocrEndpointField.text === root.info.ocr?.remoteEndpoint
                onClicked: { root.error = ""; ocrServerVerifyProc.running = true }
              }
              CopyNote { width: parent.width; text: i18n.text("server.ocrStatus", {status:root.remoteOcrStatusLabel()}) }
              CopyNote { width: parent.width; text: i18n.text("server.ocrModelManaged") }
            }
            Column {
              width: parent.width
              visible: root.settingsPage === "keys"
              enabled: visible
              spacing: Style.spacing.controlGap
              CopyNote { width: parent.width; text: i18n.text(!root.bindingInfoLoaded ? "keys.loading" : root.bindingInfo.installed ? "keys.description" : "keys.notInstalled") }
              CopyLabel { width: parent.width; visible: root.bindingInfoLoaded && (root.bindingInfo.conflicts || []).length > 0; text: i18n.text("keys.conflict", {chords:(root.bindingInfo.conflicts || []).join(", ")}) }
              PanelAction { width: parent.width; visible: root.bindingInfoLoaded && !root.bindingInfo.installed; enabled: !root.bindingBusy && root.bindingInfo.canInstall === true; text: i18n.text("keys.install"); iconText: root.glyphs.keys; onClicked: root.installBindings() }
              Column {
                width: parent.width
                visible: root.bindingInfoLoaded && root.bindingInfo.installed
                enabled: visible
                spacing: Style.space(3)
                Repeater {
                  model: root.bindingActions
                  delegate: PanelAction {
                    id: shortcutButton
                    required property var modelData
                    width: parent.width
                    height: Style.space(42)
                    text: ""
                    bordered: false
                    selected: root.bindingAction === modelData.key
                    enabled: !root.bindingBusy
                    Accessible.name: i18n.text("shortcut." + modelData.key) + ", " + (root.shortcutChord(modelData) || i18n.text("keys.unassigned"))
                    onClicked: root.beginBindingEdit(modelData, shortcutButton)
                    Text {
                      id: shortcutGlyph
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: root.shortcutIcon(shortcutButton.modelData.key)
                      color: shortcutButton.selected ? shortcutButton._selectedColor : shortcutButton.foreground
                      font.family: root.ff
                      font.pixelSize: Style.font.icon
                      Accessible.ignored: true
                    }
                    Column {
                      anchors.left: shortcutGlyph.right
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.leftMargin: Style.spacing.controlGap
                      anchors.rightMargin: Style.space(6)
                      CopyLabel { width: parent.width; text: i18n.text("shortcut." + shortcutButton.modelData.key); font.pixelSize: Style.font.bodySmall; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                      CopyNote { width: parent.width; text: root.shortcutChord(shortcutButton.modelData) || i18n.text("keys.unassigned"); wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    }
                  }
                }
              }
              Column {
                id: bindingEditor
                width: parent.width
                visible: root.bindingAction !== "" && root.bindingInfo.installed
                enabled: visible
                spacing: Style.spacing.controlGap
                PanelSeparator { width: parent.width; foreground: Host.Color.popups.text }
                PanelHeading { text: i18n.text("keys.edit", {action:i18n.text("shortcut." + root.bindingAction)}); iconText: root.shortcutIcon(root.bindingAction) }
                TextField {
                  id: chordField
                  width: parent.width
                  text: ""
                  maximumLength: 80
                  foreground: Host.Color.popups.text
                  selectByMouse: true
                  placeholderText: i18n.text("keys.placeholder")
                  onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { root.reveal(chordField) })
                  onTextChanged: root.bindingDraft = text
                  onAccepted: if (!root.bindingRecording) root.saveBinding()
                  Keys.onPressed: function(event) {
                    if (!root.bindingRecording) return
                    if (event.key === Qt.Key_Escape) { root.bindingRecording = false; event.accepted = true; return }
                    if ([Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta].indexOf(event.key) < 0) {
                      var chord = root.shortcutFromKey(event)
                      if (chord) { chordField.text = chord; root.bindingRecording = false }
                    }
                    event.accepted = true
                  }
                }
                PanelAction { width: parent.width; text: i18n.text(root.bindingRecording ? "keys.recording" : "keys.record"); iconText: root.bindingRecording ? root.glyphs.stop : root.glyphs.keys; selected: root.bindingRecording; onClicked: { root.bindingRecording = !root.bindingRecording; if (root.bindingRecording) chordField.forceActiveFocus() } }
                CopyNote { width: parent.width; text: i18n.text("keys.clearHint") }
                Row {
                  width: parent.width
                  spacing: Style.spacing.controlGap
                  PanelAction { width: (parent.width - parent.spacing) / 2; text: i18n.text("action.save"); iconText: root.glyphs.save; enabled: !root.bindingBusy; onClicked: root.saveBinding() }
                  PanelAction { width: (parent.width - parent.spacing) / 2; text: i18n.text("action.cancel"); iconText: root.glyphs.cancel; enabled: !root.bindingBusy; onClicked: root.cancelEditor() }
                }
              }
            }
          }
        }
      }
    }
  }
}
