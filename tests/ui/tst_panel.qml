import QtQuick 6.11
import QtTest
import qs.Commons
import "PLUGIN_PATH" as Plugin

TestCase {
  id: testCase
  name: "TeraPanelOffscreen"
  when: windowShown
  visible: true
  width: 760
  height: 1080
  property string output: "CAPTURE_PATH"
  property string itemA: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  property string itemB: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  Component { id: streamComponent; Plugin.StateStream { executable: "/inert/speak" } }
  Component { id: iconComponent; Plugin.TeraIcon {} }
  Component { id: barComponent; Plugin.TeraBar {} }

  Item {
    id: surface
    width: 380
    height: 540
    scale: 2
    transformOrigin: Item.TopLeft
    Rectangle { anchors.fill: parent; color: Color.popups.background }
    QtObject {
      id: widget
      property var liveState: ({status:"idle", busy:false})
      property bool speaking: liveState.status === "playing"
    }
    Plugin.TeraPanel {
      id: panel
      width: 380
      height: 540
      hostWidget: widget
    }
  }

  function control(name) { var c = findChild(panel, name); verify(c !== null, name); return c }
  function nodes(item) {
    var result = [item]
    var children = item.children || []
    for (var i = 0; i < children.length; i++) result = result.concat(nodes(children[i]))
    return result
  }
  function button(text) {
    var items = nodes(panel).filter(function(item) {
      return item.visible && item.text === text && typeof item.clicked === "function"
    })
    verify(items.length > 0, "button: " + text)
    return items[0]
  }
  function save(name) {
    var oldScale = surface.scale
    surface.scale = 2
    wait(100)
    grabImage(testCase).save(output + "/" + name + ".png")
    surface.scale = oldScale
  }
  function page(name) {
    if (["voice", "screen", "server", "keys"].indexOf(name) >= 0) panel.selectSettings(name)
    else panel.selectPage(name)
    wait(40)
  }
  function captureBottom(name) {
    wait(60)
    var v = control("viewport")
    v.contentY = Math.max(0, v.contentHeight - v.height)
    save(name)
  }
  function settings() {
    return {
      provider:"teratts", voice:"ru_f1", rate:1, endpoint:"https://tts.example.test",
      voices:[{value:"ru_f1",label:"ru_f1"},{value:"ru_m1",label:"ru_m1"}],
      keySource:"none", ui:{exportFormat:"mp3",sampleIsDefault:true},
      ocr:{engine:"remote",remoteEndpoint:"https://ocr.example.test", langs:"rus+eng",
        engines:[{name:"remote",title:"Remote OCR",status:"ready",kind:"remote"},
                 {name:"tesseract",title:"Tesseract",status:"ready",kind:"local"}],
        languages:[{value:"rus",label:"Русский",installed:true},
                   {value:"eng",label:"English",installed:true}]}
    }
  }
  function items() {
    return [{id:itemA,filename:"teratts-test-" + itemA + ".mp3",createdAt:"2026-10-12T14:25:00Z",durationMs:30000,voice:"ru_f1",rate:1,bytes:16000},
            {id:itemB,filename:"teratts-test-" + itemB + ".ogg",createdAt:"2026-10-12T14:10:00Z",durationMs:62000,voice:"ru_m1",rate:1,bytes:32000}]
  }
  function init() {
    surface.scale = 1
    panel.error = ""
    panel.info = settings()
    panel.infoLoaded = true
    panel.voiceBusy = false
    panel.infoBusy = false
    panel.refreshQueued = false
    panel.queue = []
    panel.writeEpoch = 0
    panel.readEpoch = 0
    panel.rateOverride = -1
    panel.pendingRate = -1
    control("rateTimer").stop()
    panel.audioMessage = ""
    panel.deleteId = ""
    panel.bindingAction = ""
    panel.bindingBusy = false
    panel.bindingDraft = ""
    panel.bindingRecording = false
    panel.keyEditing = false
    panel.keySaved = false
    panel.pendingKey = ""
    panel.pendingSpeech = ""
    panel.audioItems = items()
    panel.bindingInfoLoaded = true
    var bindings = {}
    panel.bindingActions.forEach(function(action) { bindings[action.key] = {chord:action.fallback} })
    panel.bindingInfo = {installed:true,canInstall:true,conflicts:[],bindings:bindings}
    widget.liveState = {status:"idle",busy:false}
    panel.settings = {locale:"ru"}
    panel.panelPage = "read"
    panel.settingsPage = "voice"
    panel.audioCreateOpen = false
    panel.exportMode = false
    panel.opened = false
    control("panelCard").availableCardHeight = 540
    control("panelCard").availableCardWidth = 380
    control("viewport").contentY = 0
    ;["audioPreviewProc","audioActionProc","audioListProc","seekProc","pauseProc","rateProc",
      "infoProc","configProc","speechProc","ocrProc","stopProc","voicesProc",
      "keyProc","ocrVerifyProc","ocrServerVerifyProc","languagesProc","bindingWriteProc","bindingsInfoProc"].forEach(function(name) {
      var process = control(name)
      process.running = false
      process.input = ""
      process.calls = []
    })
    ;["voiceDropdown", "exportSourceDropdown", "exportFormatDropdown", "ocrEngineDropdown", "ocrLanguageDropdown"].forEach(function(name) {
      control(name).close()
    })
    control("content").forceActiveFocus()
    wait(30)
  }

  function test_panel_geometry_across_pages_and_states() {
    var card = control("panelCard")
    var viewport = control("viewport")
    var tabs = control("pageTabs")
    var tabLabels = ["Читать", "Файлы", "Настройки"]
    var pages = ["read", "audio", "settings"]
    var bounds = []
    ;[540, 380].forEach(function(availableHeight) {
      card.availableCardHeight = availableHeight
      page("read")
      var width = card.width, height = card.height
      var tabY = tabs.mapToItem(control("content"), 0, 0).y
      var viewportY = viewport.y, viewportHeight = viewport.height
      var footerY = control("footer").y
      verify(height <= availableHeight)
      function check(state) {
        wait(30)
        compare(card.width, width, state + " width")
        compare(card.height, height, state + " height")
        verify(viewport.height > 0, state + " viewport")
        var position = tabs.mapToItem(control("content"), 0, 0)
        fuzzyCompare(position.y, tabY, .1, state + " navigation anchor")
        fuzzyCompare(viewport.y, viewportY, .1, state + " viewport anchor")
        fuzzyCompare(viewport.height, viewportHeight, .1, state + " viewport height")
        fuzzyCompare(control("footer").y, footerY, .1, state + " fixed controls")
        verify(position.y >= 0 && position.y + tabs.height <= control("content").height)
        bounds.push({availableHeight:availableHeight,state:state,width:card.width,height:card.height,
                     viewportHeight:viewport.height,contentHeight:viewport.contentHeight})
      }
      pages.forEach(function(name, i) {
        var tab = button(tabLabels[i])
        mouseClick(tab, tab.width / 2, tab.height / 2)
        compare(panel.panelPage, name)
        check(name)
      })
      ;["voice", "screen", "server", "keys"].forEach(function(name) {
        page(name); compare(panel.settingsPage, name); check("settings " + name)
      })
      page("audio")
      panel.audioCreateOpen = true
      check("create disclosure")
      panel.audioCreateOpen = false
      panel.audioItems = []
      check("empty library")
      panel.audioItems = items()
      widget.liveState = {status:"playing",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:10000}
      check("preview playing")
      panel.deleteId = itemA
      check("delete confirmation")
      panel.deleteId = ""
      ;["preparing","playing","paused","error"].forEach(function(status) {
        widget.liveState = {status:status,kind:"speech",busy:status !== "error",durationMs:30000}
        check("speech " + status)
        if (availableHeight === 540 && status === "playing") save("geometry-speech-playing")
      })
      widget.liveState = {status:"idle",busy:false}
      page("server")
      panel.keyEditing = true
      check("token editor")
      panel.keyEditing = false
      var endpoint = control("ocrEndpointField")
      endpoint.forceActiveFocus()
      wait(60)
      var pos = endpoint.mapToItem(viewport, 0, 0)
      verify(pos.y >= -1 && pos.y + endpoint.height <= viewport.height + 1,
             "focused OCR endpoint stays within the viewport")
      compare(card.height, height)
      if (availableHeight === 380) save("geometry-small-server-focused")
      page("keys")
      panel.beginBindingEdit(panel.bindingActions[0])
      check("shortcut editor")
      panel.cancelEditor()
      page("read")
      check("return to read")
      panel.settings = {locale:"en"}
      pages.forEach(function(name) { page(name); check("en " + name) })
      panel.settings = {locale:"ru"}
    })
    card.availableCardHeight = 540
    console.log("PANEL_GEOMETRY " + JSON.stringify(bounds))
  }

  function test_all_pages_and_states() {
    ;["read","voice","screen","keys","server","audio"].forEach(function(name) {
      page(name); save("ru-" + name); captureBottom("ru-" + name + "-bottom")
    })
    var local = settings(); local.ocr.engine = "tesseract"; panel.info = local
    page("screen"); save("ru-screen-tesseract"); captureBottom("ru-screen-tesseract-bottom")
    panel.info = settings()
    panel.bindingInfo = {installed:false,canInstall:true,conflicts:[],bindings:{}}
    page("keys"); save("ru-keys-not-installed")
    panel.bindingInfo = {installed:true,canInstall:true,conflicts:["SUPER + SHIFT + L"],bindings:{}}
    save("ru-keys-conflict")
    panel.beginBindingEdit(panel.bindingActions[0]); captureBottom("ru-keys-editor")
    page("server"); panel.keyEditing = true; save("ru-server-token-edit")
    page("audio")
    panel.audioItems = []
    panel.audioRefreshQueued = false
    control("audioListProc").finish(0, 0, "[]", "")
    wait(30)
    compare(control("audioListProc").running, false)
    verify(nodes(panel).some(function(item) {
      return item.visible && item.text === control("i18n").text("audio.empty")
    }))
    save("ru-audio-empty")
    panel.audioItems = items()
    widget.liveState = {status:"preparing",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:0}
    save("ru-audio-preparing")
    widget.liveState = {status:"playing",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:12000,playbackRate:1,bands:[.2,.6,.4,.1]}
    save("ru-audio-playing")
    widget.liveState = {status:"paused",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:12000,playbackRate:1}
    save("ru-audio-paused"); captureBottom("ru-audio-paused-bottom")
    widget.liveState = {status:"exporting",kind:"export",busy:true}
    control("viewport").contentY = 0; save("ru-audio-exporting")
    widget.liveState = {status:"error",busy:false,errorCode:"storage_full"}
    panel.error = control("i18n").text("audio.error.storage_full")
    save("ru-audio-error")
    widget.liveState = {status:"idle",busy:false}; panel.error = ""
    panel.settings = {locale:"en"}
    ;["read","voice","screen","keys","server","audio"].forEach(function(name) { page(name); save("en-" + name) })
  }

  function test_delete_and_copy_dispatch_while_preview_is_running() {
    page("audio")
    panel.previewAudio(itemA)
    var preview = control("audioPreviewProc")
    verify(preview.running)
    widget.liveState = {status:"playing",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:10000}
    wait(40)
    var deleteButton = button("Удалить")
    verify(deleteButton.enabled)
    var copyButton = button("Копировать")
    verify(copyButton.enabled)
    var viewport = control("viewport")
    // The player pushes library actions below the fixed viewport: scroll first.
    for (var i = 0; i < 12; i++) {
      var position = copyButton.mapToItem(viewport, 0, 0)
      if (position.y >= 0 && position.y + copyButton.height <= viewport.height) break
      mouseWheel(viewport, viewport.width / 2, viewport.height / 2, 0, -120)
      wait(30)
    }
    tryCompare(viewport, "moving", false, 2000)
    var copyPosition = copyButton.mapToItem(viewport, 0, 0)
    verify(copyPosition.y >= 0 && copyPosition.y + copyButton.height <= viewport.height)
    mouseClick(copyButton, copyButton.width / 2, copyButton.height / 2)
    var action = control("audioActionProc")
    compare(action.command[1], "--audio-copy")
    compare(action.command[2], itemA)
    verify(!preview.stopping)
    action.finish(0, 0, "", "")
    if (control("audioListProc").running) control("audioListProc").finish(0, 0, JSON.stringify(items()), "")
    // Refresh replaces the delegates. Resolve the current row before clicking.
    wait(40)
    deleteButton = button("Удалить")
    panel.reveal(deleteButton)
    mouseClick(deleteButton, deleteButton.width / 2, deleteButton.height / 2)
    compare(action.running, false)
    compare(panel.deleteId, itemA)
    verify(!preview.stopping)
    wait(30)
    save("ru-audio-delete-confirm")
    var confirmButtons = nodes(panel).filter(function(item) {
      return item.visible && item.text === "Удалить" && typeof item.clicked === "function"
    })
    verify(confirmButtons.length >= 2)
    // The inline confirmation can extend below the clipped viewport.
    panel.reveal(confirmButtons[1])
    wait(40)
    mouseClick(confirmButtons[1], confirmButtons[1].width / 2, confirmButtons[1].height / 2)
    compare(action.command[1], "--audio-delete")
    compare(action.command[2], itemA)
    verify(action.running)
    verify(preview.stopping)
    action.finish(0, 0, "", "")
    preview.finish(143, 0, "", "")
    compare(panel.error, "")
    control("audioListProc").finish(0, 0, JSON.stringify(items().slice(1)), "")
    wait(30)
    if (control("audioListProc").running) control("audioListProc").finish(0, 0, JSON.stringify(items().slice(1)), "")
    compare(panel.audioItems.length, 1)
    compare(panel.audioItems[0].id, itemB)
  }

  function clickControl(item) {
    panel.reveal(item)
    wait(30)
    mouseClick(item, item.width / 2, item.height / 2)
  }

  function chooseNext(dropdown) {
    panel.reveal(dropdown)
    wait(30)
    mouseClick(dropdown, dropdown.width / 2, dropdown.height / 2)
    tryCompare(dropdown, "popupOpen", true, 1000, dropdown.objectName)
    keyClick(Qt.Key_Down)
    keyClick(Qt.Key_Return)
    tryCompare(dropdown, "popupOpen", false)
  }

  function acceptConfig(result) {
    control("configProc").finish(0, 0, "", "")
    wait(30)
    if (control("infoProc").running) control("infoProc").finish(0, 0, JSON.stringify(result), "")
    wait(30)
    if (control("infoProc").running) control("infoProc").finish(0, 0, JSON.stringify(result), "")
    wait(30)
    compare(control("configProc").running, false)
  }

  function test_redesign_read_actions_and_navigation() {
    ;["selection", "clipboard"].forEach(function(source) {
      page("read")
      var action = control(source + "Button")
      verify(action.enabled)
      clickControl(action)
      compare(control("speechProc").command[1], "--" + source)
      compare(control("speechProc").input, "", "no private text on argv or incidental stdin")
      verify(control("speechProc").running)
      verify(!action.enabled)
      control("speechProc").finish(0, 0, "", "")
    })
    var modes = [{mode:"snip",label:"Область"}, {mode:"window",label:"Окно"}, {mode:"screen",label:"Монитор"}]
    modes.forEach(function(item) {
      page("read")
      clickControl(button(item.label))
      compare(control("ocrProc").command[1], "--" + item.mode)
      compare(control("ocrProc").environment.TTS_CAPTURE_DELAY, "0.25")
      verify(control("ocrProc").running)
      compare(panel.requestedPage, "read")
      control("ocrProc").finish(0, 0, "", "")
    })
    page("read")
    clickControl(control("ocrSettingsButton"))
    compare(panel.panelPage, "settings")
    compare(panel.settingsPage, "screen")
    clickControl(button("Сервер"))
    compare(panel.settingsPage, "server")
    clickControl(button("Клавиши"))
    compare(panel.settingsPage, "keys")
    clickControl(button("Голос"))
    compare(panel.settingsPage, "voice")
    clickControl(button("Читать"))
    compare(panel.panelPage, "read")
    clickControl(control("slowerButton"))
    compare(panel.rateValue, .9)
    control("configProc").finish(0, 0, "", "")
    clickControl(control("fasterButton"))
    compare(panel.rateValue, 1)
    page("audio")
    var focus = control("createToggle")
    focus.forceActiveFocus()
    keyClick(Qt.Key_Space)
    verify(panel.audioCreateOpen)
    keyClick(Qt.Key_Return)
    verify(!panel.audioCreateOpen)
  }

  function test_redesign_voice_dropdown_and_popup_escape() {
    page("read")
    var voice = control("voiceDropdown")
    mouseClick(voice, voice.width / 2, voice.height / 2)
    tryCompare(voice, "popupOpen", true)
    keyClick(Qt.Key_Escape)
    tryCompare(voice, "popupOpen", false)
    verify(!control("configProc").running, "browse and dismiss never save")
    chooseNext(voice)
    compare(control("configProc").command[2], ".teratts.voice")
    compare(control("configProc").input, '"ru_m1"\n')
    verify(panel.voiceBusy)
    control("configProc").finish(0, 0, "", "")
    control("infoProc").finish(0, 0, JSON.stringify(settings()), "")
    clickControl(control("refreshButton"))
    verify(control("voicesProc").running)
    control("voicesProc").finish(0, 0, "", "")
    page("voice")
    panel.sampleText = "Fixture speech <text>"
    clickControl(control("testButton"))
    compare(control("speechProc").command[1], "--stdin-json")
    compare(control("speechProc").input, JSON.stringify(panel.sampleText) + "\n")
    verify(control("speechProc").command.join(" ").indexOf(panel.sampleText) < 0)
    control("speechProc").finish(0, 0, "", "")
  }

  function test_redesign_file_creation_keeps_library_and_sources() {
    page("audio")
    verify(!panel.audioCreateOpen)
    verify(control("audioRows").count === 2)
    clickControl(control("createToggle"))
    verify(panel.audioCreateOpen)
    var source = control("exportSourceDropdown")
    var format = control("exportFormatDropdown")
    chooseNext(source)
    compare(panel.exportSource, "clipboard")
    chooseNext(format)
    compare(panel.exportFormat, "ogg")
    compare(control("configProc").command[2], ".ui.exportFormat")
    clickControl(control("createAudioButton"))
    compare(control("audioActionProc").command.join(" "), panel.speakBin + " --export-audio --format ogg --clipboard")
    verify(!control("createAudioButton").enabled)
    control("audioActionProc").finish(0, 0, JSON.stringify(items()[0]), "")
    compare(panel.audioMessage, control("i18n").text("audio.ready"))
    widget.liveState = {status:"exporting",kind:"export",busy:true}
    verify(control("stopButton").enabled)
    verify(!control("pauseButton").enabled)
    clickControl(control("stopButton"))
    verify(control("stopProc").running)
    widget.liveState = {status:"playing",kind:"preview",audioId:itemA,busy:true,durationMs:30000}
    clickControl(control("pauseButton"))
    compare(control("pauseProc").command[1], "--pause-toggle")
    control("pauseProc").finish(0, 0, "", "")
    widget.liveState = {status:"paused",kind:"preview",audioId:itemA,busy:true,durationMs:30000}
    compare(control("pauseButton").text, control("i18n").text("action.resume"))
    clickControl(button("Открыть папку"))
    compare(control("audioActionProc").command[1], "--audio-open-folder")
  }

  function test_redesign_speed_available_during_speech_and_preview() {
    widget.liveState = {status:"playing",kind:"speech",busy:true,playbackRate:1}
    ;["audio", "voice", "screen", "server", "keys"].forEach(function(name) {
      page(name)
      verify(control("rateControl").visible, "speech rate accessible on " + name)
      verify(control("speedSlider").enabled)
    })
    widget.liveState = {status:"playing",kind:"preview",audioId:itemA,busy:true,durationMs:30000,playbackRate:1}
    page("audio")
    clickControl(control("fasterButton"))
    compare(control("rateProc").command[1], "--playback-rate")
    compare(control("rateProc").command[2], "1.1")
    verify(!control("configProc").running, "preview rate never saves speech preference")
    widget.liveState = {status:"exporting",kind:"export",busy:true}
    verify(!control("rateControl").visible)
    page("read")
    verify(control("rateControl").visible)
  }

  function test_redesign_endpoints_sample_and_keyboard_reachability() {
    var fresh = settings(); fresh.endpoint = ""
    panel.info = fresh
    page("server")
    var endpoint = control("endpointField")
    compare(endpoint.text, "")
    compare(endpoint.placeholderText, "https://tts.example.com")
    verify(!control("configProc").running, "A placeholder is not a saved endpoint")
    endpoint.forceActiveFocus()
    keyClick(Qt.Key_A, Qt.ControlModifier)
    endpoint.text = "https://changed.example.test"
    control("tokenButton").forceActiveFocus()
    wait(40)
    compare(control("configProc").command[2], ".teratts.endpoint")
    verify(control("configProc").input.indexOf("https://changed.example.test") >= 0)
    acceptConfig(settings())
    var ocr = control("ocrEndpointField")
    panel.reveal(ocr)
    ocr.forceActiveFocus()
    keyClick(Qt.Key_A, Qt.ControlModifier)
    ocr.text = "https://ocr.changed.example.test"
    control("tokenButton").forceActiveFocus()
    wait(40)
    compare(control("configProc").command[2], ".ocr.remote.endpoint")
    verify(control("configProc").input.indexOf("https://ocr.changed.example.test") >= 0)
    acceptConfig(settings())
    page("voice")
    var sample = control("sampleField")
    sample.forceActiveFocus()
    keyClick(Qt.Key_A, Qt.ControlModifier)
    sample.text = "Changed fixture phrase"
    control("testButton").forceActiveFocus()
    wait(40)
    compare(control("configProc").command[2], ".ui.sampleText")
    verify(control("configProc").input.indexOf("Changed fixture phrase") >= 0)
    page("keys")
    var card = control("panelCard"), viewport = control("viewport")
    card.availableCardHeight = 380
    control("content").forceActiveFocus()
    for (var i = 0; i < 24; i++) {
      keyClick(Qt.Key_Tab)
      wait(30)
      var active = testCase.Window.window.activeFocusItem
      verify(active !== null)
      var ancestor = active
      while (ancestor && ancestor !== viewport.contentItem) ancestor = ancestor.parent
      if (ancestor) {
        var pos = active.mapToItem(viewport, 0, 0)
        verify(pos.y >= -1 && pos.y + active.height <= viewport.height + 1, "Tab focus is visible: " + active.objectName)
      }
    }
    card.availableCardHeight = 540
  }

  function test_redesign_settings_and_private_token() {
    page("server")
    clickControl(control("tokenButton"))
    verify(panel.keyEditing)
    var key = control("keyField")
    verify(key.password)
    key.text = "fixture-token-123"
    clickControl(control("keyButton"))
    compare(key.text, "")
    compare(control("keyProc").command[1], "key-store")
    compare(control("keyProc").input, "fixture-token-123\n")
    verify(control("keyProc").command.join(" ").indexOf("fixture-token") < 0)
    control("keyProc").finish(0, 0, '{"ok":true}', "")
    verify(!panel.keyEditing)
    verify(panel.keySaved)
    wait(30)
    if (control("infoProc").running) control("infoProc").finish(0, 0, JSON.stringify(settings()), "")
    wait(30)
    page("screen")
    var engine = control("ocrEngineDropdown")
    chooseNext(engine)
    compare(control("configProc").command[2], ".ocr.engine")
    compare(control("configProc").input, '"tesseract"\n')
    var local = settings(); local.ocr.engine = "tesseract"
    acceptConfig(local)
    compare(panel.info.ocr.engine, "tesseract")
    verify(control("ocrLanguageDropdown").visible)
    chooseNext(control("ocrLanguageDropdown"))
    compare(control("configProc").command[2], ".ocr.tesseract.langs")
    clickControl(button(control("i18n").text("screen.refreshLanguages")))
    verify(control("languagesProc").running)
    control("languagesProc").finish(0, 0, "", "")
    clickControl(button(control("i18n").text("screen.verifyOcr")))
    compare(control("ocrVerifyProc").command[1], "--verify-ocr")
    compare(control("ocrVerifyProc").command[2], "tesseract")
    control("ocrVerifyProc").finish(0, 0, "", "")
    control("configProc").finish(0, 0, "", "")
    if (control("infoProc").running) control("infoProc").finish(0, 0, JSON.stringify(local), "")
    page("server")
    clickControl(button(control("i18n").text("server.verifyOcr")))
    compare(control("ocrServerVerifyProc").command[2], "remote")
    clickControl(control("tokenButton"))
    key.text = "unsaved-fixture-token"
    page("voice")
    verify(!panel.keyEditing)
    compare(key.text, "")
  }

  function test_redesign_shortcut_edit_record_clear_and_focus() {
    page("keys")
    var action = nodes(panel).filter(function(item) {
      return item.visible && item.modelData && item.modelData.key === "stop" && typeof item.clicked === "function"
    })[0]
    clickControl(action)
    compare(panel.bindingAction, "stop")
    wait(40)
    var field = control("chordField")
    tryCompare(field, "activeFocus", true, 1000)
    tryVerify(function() {
      var pos = field.mapToItem(control("viewport"), 0, 0)
      return pos.y >= -1 && pos.y + field.height <= control("viewport").height + 1
    }, 1000, "focused shortcut editor is revealed after layout")
    clickControl(button(control("i18n").text("keys.record")))
    verify(panel.bindingRecording)
    keyClick(Qt.Key_F12, Qt.ControlModifier | Qt.AltModifier)
    compare(panel.bindingDraft, "CTRL + ALT + F12")
    verify(!panel.bindingRecording)
    clickControl(button(control("i18n").text("action.save")))
    compare(control("bindingWriteProc").command.slice(-3).join("|"), "set|stop|CTRL + ALT + F12")
    control("bindingWriteProc").finish(1, 0, "", "conflict")
    verify(panel.bindingAction === "stop", "failed save retains edit")
    verify(panel.error !== "")
    field.text = ""
    compare(panel.bindingDraft, "")
    wait(40)
    clickControl(button(control("i18n").text("action.save")))
    compare(control("bindingWriteProc").command.slice(-3).join("|"), "set|stop|")
    control("bindingWriteProc").finish(0, 0, "", "")
    verify(panel.bindingAction === "")
    control("bindingsInfoProc").finish(0, 0, JSON.stringify({installed:true,conflicts:[],bindings:{stop:{chord:""}}}), "")
    verify(control("cancelHint").text.indexOf("SUPER + ALT + X") < 0)
    panel.bindingInfo = {installed:false,canInstall:true,conflicts:[],bindings:{}}
    clickControl(button(control("i18n").text("keys.install")))
    compare(control("bindingWriteProc").command.slice(-1)[0], "install")
  }

  function test_screen_export_success_feedback() {
    page("audio")
    panel.exportSource = "snip"
    panel.openPage("audio")
    panel.createAudio()
    compare(panel.opened, false)
    tryCompare(control("ocrProc"), "running", true, 1000)
    compare(control("ocrProc").command[1], "--export-audio")
    compare(control("ocrProc").command[4], "--snip")
    control("ocrProc").finish(0, 0, JSON.stringify(items()[0]), "")
    compare(panel.audioMessage, control("i18n").text("audio.ready"))
    compare(panel.opened, false)
    panel.opened = true
    compare(panel.panelPage, "audio")
    wait(30)
    save("ru-audio-export-complete")
  }

  function test_stop_owns_screen_preparation_immediately() {
    panel.readScreen("snip")
    // Closing the panel must not leave an unregistered launch timer.
    verify(control("ocrProc").running, "capture must be owned before cancellation")
    panel.stop()
    verify(control("stopProc").running)
    compare(control("stopProc").command[1], "--stop")
    control("ocrProc").finish(0, 0, "", "")
    compare(panel.ocrBusy, false)
    compare(panel.error, "")
  }

  function test_stop_shortcut_is_visible_on_every_page() {
    var hint = findChild(panel, "cancelHint")
    verify(hint !== null, "fixed cancellation hint")
    ;["read","voice","screen","keys","server","audio"].forEach(function(name) {
      page(name)
      verify(hint.visible)
      verify(hint.text.indexOf("SUPER + ALT + X") >= 0)
    })
    panel.bindingInfo = {installed:true,conflicts:[],bindings:{stop:{chord:"SUPER + CTRL + F12"}}}
    verify(hint.text.indexOf("SUPER + CTRL + F12") >= 0)
    var tabY = control("pageTabs").y
    var cardHeight = control("panelCard").height
    panel.bindingInfo = {installed:true,conflicts:["SUPER + ALT + X"],bindings:{stop:{chord:"SUPER + ALT + X"}}}
    verify(hint.text.indexOf("SUPER + ALT + X") < 0, "conflicting shortcut is not advertised")
    panel.bindingInfo = {installed:true,conflicts:[],bindings:{stop:null}}
    verify(hint.text.indexOf("SUPER + ALT + X") < 0)
    panel.bindingInfo = {installed:true,conflicts:[],bindings:{stop:{chord:""}}}
    verify(hint.text.indexOf("SUPER + ALT + X") < 0)
    wait(20)
    compare(control("pageTabs").y, tabY, "disabled shortcut keeps navigation stable")
    panel.bindingInfoLoaded = false
    verify(hint.text.indexOf("SUPER + ALT + X") < 0)
    wait(20)
    compare(control("pageTabs").y, tabY, "loading shortcut keeps navigation stable")
    compare(control("panelCard").height, cardHeight)
    widget.liveState = {status:"playing",kind:"speech",busy:true}
    wait(30)
    var stopButton = button("Стоп")
    mouseClick(stopButton, stopButton.width / 2, stopButton.height / 2)
    verify(control("stopProc").running)
  }

  function test_screen_export_cancel_is_not_an_io_error() {
    page("audio")
    panel.exportMode = true
    control("ocrProc").running = true
    control("ocrProc").finish(0, 0, "", "")
    compare(panel.error, "")
    compare(panel.audioMessage, "")
    compare(panel.exportMode, false)
    // Only empty success is cancellation; malformed nonempty results still fail.
    panel.exportMode = true
    control("ocrProc").running = true
    control("ocrProc").finish(0, 0, "invalid json", "")
    compare(panel.error, control("i18n").text("audio.error.io"))
  }

  function test_seek_keys_and_slider_release_dispatch() {
    page("audio")
    widget.liveState = {status:"paused",kind:"preview",audioId:itemA,busy:true,durationMs:30000,positionMs:12000}
    var seek = control("audioSeekSlider")
    verify(seek.enabled)
    seek.forceActiveFocus()
    keyClick(Qt.Key_Right)
    compare(control("seekProc").command[2], "17")
    control("seekProc").finish(0, 0, "", "")
    seek.forceActiveFocus(); keyClick(Qt.Key_Home)
    compare(control("seekProc").command[2], "0")
    control("seekProc").finish(0, 0, "", "")
    seek.forceActiveFocus(); keyClick(Qt.Key_End)
    compare(control("seekProc").command[2], "30")
    control("seekProc").finish(0, 0, "", "")
    wait(30)
    mouseClick(seek, seek.width / 2, seek.height / 2)
    compare(Number(control("seekProc").command[2]), 15)
  }

  function test_info_failure_state_and_recovery() {
    page("read")
    if (control("infoProc").running)
      control("infoProc").finish(0, 0, JSON.stringify(settings()), "")
    wait(20)
    panel.setConfig(".teratts.voice", "ru_m1")
    verify(panel.voiceBusy)
    control("configProc").finish(0, 0, "", "")
    wait(20)
    control("infoProc").finish(1, 0, "", "fixture info failure")
    verify(!panel.voiceBusy)
    verify(control("voiceDropdown").enabled)
    compare(panel.error, control("i18n").text("error.info"))
    save("ru-voice-info-error")
    panel.refresh()
    control("infoProc").finish(0, 0, JSON.stringify(settings()), "")
    compare(panel.voiceBusy, false)
    verify(control("voiceDropdown").enabled)
  }

  function test_fixed_navigation_keyboard_speed_and_long_shortcuts() {
    page("audio")
    var many = []
    for (var i = 0; i < 20; i++) {
      var item = items()[0]
      item.id = String(i).padStart(32, "0")
      item.filename = "teratts-test-" + item.id + ".mp3"
      many.push(item)
    }
    panel.audioItems = many
    captureBottom("ru-audio-library-bottom")
    verify(control("viewport").contentY > 1000)
    var tabs = control("pageTabs")
    verify(tabs.mapToItem(control("content"), 0, 0).y >= 0)
    var readTab = button("Читать")
    mouseClick(readTab, readTab.width / 2, readTab.height / 2)
    compare(panel.panelPage, "read")
    var speed = control("speedSlider")
    verify(speed.activeFocusOnTab)
    speed.forceActiveFocus(); keyClick(Qt.Key_Right)
    compare(panel.rateValue, 1.05)
    compare(control("configProc").command[2], ".rate")
    control("configProc").finish(0, 0, "", "")
    speed.forceActiveFocus(); keyClick(Qt.Key_End)
    compare(panel.rateValue, 4)
    page("keys")
    var chord = "SUPER + CTRL + ALT + SHIFT + F12"
    panel.bindingInfo = {installed:true,canInstall:true,conflicts:[],bindings:{selection:{chord:chord}}}
    wait(40)
    var shortcut = nodes(panel).filter(function(item) {
      return item.visible && item.modelData && item.modelData.key === "selection" && typeof item.clicked === "function"
    })[0]
    verify(shortcut !== undefined)
    var labels = nodes(shortcut).filter(function(item) { return item.text === chord && typeof item.clicked !== "function" })
    verify(labels.length > 0)
    verify(labels[0].width <= shortcut.width)
    verify(labels[0].implicitWidth <= labels[0].width, "long chord fits without elision")
    save("ru-keys-long-chord")
  }

  function test_escape_cancels_editor_and_delete_without_side_effects() {
    panel.openPage("settings")
    page("keys")
    panel.bindingInfoLoaded = true
    panel.bindingInfo = {installed:true,canInstall:true,conflicts:[],bindings:{}}
    panel.beginBindingEdit(panel.bindingActions[0])
    wait(30)
    control("chordField").forceActiveFocus()
    keyClick(Qt.Key_Escape)
    verify(panel.opened)
    compare(panel.bindingAction, "")
    page("audio")
    var deleteButton = button("Удалить")
    mouseClick(deleteButton, deleteButton.width / 2, deleteButton.height / 2)
    compare(panel.deleteId, itemA)
    wait(30); keyClick(Qt.Key_Escape)
    compare(panel.deleteId, "")
    verify(panel.opened)
    verify(!control("audioActionProc").running)
    verify(deleteButton.activeFocus)
    keyClick(Qt.Key_Escape)
    verify(!panel.opened)
  }

  function test_state_stream_exit_failed_start_stall_and_recovery() {
    var stream = streamComponent.createObject(surface)
    verify(stream !== null)
    var subscriber = findChild(stream, "subscriber")
    var retry = findChild(stream, "retryTimer")
    var watchdog = findChild(stream, "watchdog")
    verify(subscriber.running)
    var playing = JSON.stringify({status:"playing",busy:true,speaking:true,bands:[.2,.7,.4,.1]})
    subscriber.stdout.read(playing)
    verify(stream.connected)
    compare(stream.liveState.bands[1], .7)
    subscriber.finish(1, 0, "", "")
    verify(!stream.connected)
    compare(stream.liveState.status, "unavailable")
    verify(retry.running)
    compare(retry.interval, 2000)
    retry.stop(); retry.triggered()
    verify(subscriber.running)
    subscriber.stdout.read(playing)
    verify(stream.connected)
    compare(stream.retryDelay, 2000)
    watchdog.triggered()
    verify(!subscriber.running)
    verify(!stream.connected)
    subscriber.stdout.read("{invalid")
    verify(!stream.connected)
    retry.stop(); retry.triggered()
    // Simulate a failed start without an exited signal: the watchdog recovers.
    subscriber.running = false
    retry.stop(); watchdog.triggered()
    verify(retry.running)
    compare(stream.liveState.bands[1], 0)
    stream.destroy()
  }

  function test_loaded_bar_status_reports_candidate_and_panel_readiness() {
    var bar = barComponent.createObject(surface)
    verify(bar !== null)
    var status = findChild(bar, "stateStream")
    var subscriber = findChild(status, "subscriber")
    subscriber.stdout.read(JSON.stringify({status:"idle",busy:false,speaking:false,bands:[0,0,0,0]}))
    var handler = findChild(bar, "runtimeStatus")
    verify(handler !== null)
    tryVerify(function() { return JSON.parse(handler.status()).panelLoaded }, 1000)
    var info = JSON.parse(handler.status())
    compare(info.version, "0.3.17")
    verify(info.connected)
    compare(info.playback, "idle")
    compare(info.opened, false)
    verify(info.source.indexOf("plugin") >= 0)
    bar.destroy()
  }

  function test_monogram_bar_clicks_keep_existing_routes_and_palette() {
    var bar = barComponent.createObject(surface)
    verify(bar !== null)
    var stream = findChild(bar, "stateStream")
    var subscriber = findChild(stream, "subscriber")
    var hit = findChild(bar, "button")
    var runner = findChild(bar, "runner")
    function state(status, busy, speaking) {
      subscriber.stdout.read(JSON.stringify({status:status,busy:busy,speaking:speaking,bands:[.2,.8,.5,.1]}))
    }
    state("idle", false, false)
    mouseClick(hit, hit.width / 2, hit.height / 2, Qt.LeftButton)
    compare(bar.opened, true)
    var loadedPanel = findChild(bar, "panelLoader").item
    findChild(loadedPanel, "content").forceActiveFocus()
    keyClick(Qt.Key_Escape)
    compare(bar.opened, false)
    ;["idle", "playing", "paused"].forEach(function(status) {
      state(status, status !== "idle", status === "playing")
      mouseClick(hit, hit.width / 2, hit.height / 2, Qt.RightButton)
      compare(runner.command[1], "--quick-action")
      compare(bar.opened, false)
    })
    var glyph = hit.children.find(function(item) { return item.levels !== undefined })
    verify(glyph !== undefined)
    compare(String(glyph.color), String(hit.activeColor))
    stream.lost()
    compare(String(glyph.color), String(Color.urgent))
    state("idle", false, false)
    compare(String(glyph.color), String(hit.foreground))
    bar.destroy()
  }

  function test_reopen_read_resets_scroll_and_keeps_requested_audio_route() {
    control("panelCard").availableCardHeight = 380
    panel.openPage("read")
    page("keys")
    panel.beginBindingEdit(panel.bindingActions[0])
    wait(60)
    var viewport = control("viewport")
    viewport.contentY = Math.max(0, viewport.contentHeight - viewport.height)
    verify(viewport.contentY > 0, "constrained editor reached bottom")
    panel.close()
    panel.openPage("read")
    wait(80)
    compare(panel.panelPage, "read")
    fuzzyCompare(viewport.contentY, 0, .1, "reopened Read starts at its primary actions")
    var selection = control("selectionButton").mapToItem(viewport, 0, 0)
    verify(selection.y >= 0 && selection.y + control("selectionButton").height <= viewport.height)
    panel.close()
    panel.openPage("audio")
    wait(60)
    compare(panel.panelPage, "audio")
    fuzzyCompare(viewport.contentY, 0, .1)
    panel.close()
  }

  function test_busy_speed_controls_do_not_pan_the_vertical_viewport() {
    page("voice")
    widget.liveState = {status:"playing",speaking:true,kind:"speech",busy:true,playbackRate:1.85}
    wait(60)
    var v = control("viewport")
    var slower = control("slowerButton")
    var faster = control("fasterButton")
    var slider = control("speedSlider")
    function bounded(label) {
      console.log("SPEED_BOUNDS " + label + " contentX=" + v.contentX + " viewport=" + v.width + " slower=" + slower.mapToItem(v, 0, 0).x + " faster=" + faster.mapToItem(v, 0, 0).x)
      fuzzyCompare(v.contentX, 0, .5, label + " vertical-only viewport")
      ;[slower,slider,faster].forEach(function(item) {
        var point = item.mapToItem(v, 0, 0)
        verify(point.x >= -.5 && point.x + item.width <= v.width + .5, label + " " + item.objectName + " clipped")
      })
    }
    bounded("opened")
    mouseClick(slower, slower.width / 2, slower.height / 2)
    wait(50)
    bounded("slower click")
    slower.forceActiveFocus()
    keyClick(Qt.Key_Tab)
    wait(50)
    bounded("slider focus")
    mouseDrag(slider, slider.width / 2, slider.height / 2, -slider.width / 4, 0)
    wait(150)
    bounded("drag left")
    mouseDrag(slider, slider.width / 2, slider.height / 2, slider.width / 4, 0)
    wait(150)
    bounded("drag right")
    mouseClick(faster, faster.width / 2, faster.height / 2)
    wait(50)
    bounded("faster click")
    control("sampleField").forceActiveFocus()
    wait(70)
    bounded("sample focus")
  }

  function test_native_control_frames_clear_the_viewport_clip_edge() {
    var v = control("viewport")
    var card = control("panelCard")
    var form = control("form")
    var inset = Style.spacing.xxs
    verify(inset > 0)
    widget.liveState = {status:"playing",speaking:true,kind:"speech",busy:true,playbackRate:1.85}
    ;[380,320].forEach(function(width) {
      card.availableCardWidth = width
      ;["ru","en"].forEach(function(locale) {
        panel.settings = {locale:locale}
        ;["read","audio","voice","server"].forEach(function(destination) {
          page(destination)
          if (destination === "audio") panel.audioCreateOpen = true
          var target = destination === "voice" ? control("sampleField")
            : destination === "server" ? control("endpointField") : control("slowerButton")
          target.forceActiveFocus()
          panel.reveal(target)
          wait(60)
          var controls = [control("slowerButton"),control("fasterButton"),control("speedSlider")]
          if (destination === "voice") controls.push(control("sampleField"))
          if (destination === "server") controls.push(control("endpointField"))
          controls.forEach(function(item) {
            var p = item.mapToItem(v, 0, 0)
            verify(p.x >= inset - .5 && p.x + item.width <= v.width - inset + .5,
              locale + " " + width + " " + destination + " " + item.objectName + " must clear clip edge; x=" + p.x)
          })
          fuzzyCompare(form.x, inset, .5)
          fuzzyCompare(form.width, v.width - inset * 2, .5)
          fuzzyCompare(v.contentX, 0, .5)
          var p = target.mapToItem(v, 0, 0)
          verify(p.y >= -.5 && p.y + target.height <= v.height + .5, "focus still revealed")
        })
      })
    })
    card.availableCardWidth = 380
  }

  function test_panel_identity_and_semantic_icons_keep_text_and_bounds() {
    var mark = control("panelIcon")
    compare(mark.iconSize, Style.font.display)
    compare(String(mark.color), String(Color.popups.text))
    compare(mark.playing, false)
    widget.liveState = {status:"playing", speaking:true, kind:"speech", busy:true, bands:[.2,.8,.5,.9]}
    compare(mark.playing, true)
    compare(mark.levels, widget.liveState.bands)
    widget.liveState = {status:"preparing", busy:true}
    compare(mark.busy, true)
    widget.liveState = {status:"paused", busy:true}
    compare(mark.playing, false)
    compare(mark.busy, false)
    var bindings = panel.bindingActions.map(function(action) { return panel.shortcutIcon(action.key) })
    compare(bindings.length, 9)
    verify(bindings.every(function(glyph) { return glyph.length > 0 }))
    var headings = nodes(panel).filter(function(item) { return typeof item.fontSize === "number" && typeof item.iconText === "string" && typeof item.clicked !== "function" && item.text })
    verify(headings.length >= 10, "section and field headings have semantic icons")
    verify(headings.every(function(item) { return item.iconText.length > 0 }))
    var buttons = [control("selectionButton"), control("clipboardButton"), control("pauseButton"), control("stopButton")]
    verify(buttons.every(function(item) { return item.text.length > 0 && item.iconText.length > 0 }))
    var checked = 0
    ;[380,320].forEach(function(availableWidth) {
      control("panelCard").availableCardWidth = availableWidth
      ;["ru","en"].forEach(function(locale) {
        panel.settings = {locale:locale}
        ;["read","audio","voice","screen","server","keys"].forEach(function(destination) {
          page(destination)
          if (destination === "audio") panel.audioCreateOpen = true
          if (destination === "server") panel.keyEditing = true
          wait(40)
          var actions = nodes(panel).filter(function(item) { return item.visible && item.text && typeof item.clicked === "function" && typeof item.iconText === "string" })
          actions.forEach(function(action) {
            if (["+","−"].indexOf(action.text) >= 0) return
            verify(action.iconText.length > 0, destination + " " + action.text + " icon")
            verify(action.width + .5 >= action.implicitWidth, locale + " width=" + availableWidth + " " + action.text + " needs " + action.implicitWidth + " has " + action.width)
            var labels = nodes(action).filter(function(item) { return item.visible && item.text === action.text && typeof item.clicked !== "function" })
            verify(labels.length > 0, "retained native text: " + action.text)
            labels.forEach(function(label) {
              var point = label.mapToItem(action, 0, 0)
              verify(point.x >= -.5 && point.x + label.width <= action.width + .5, "native text stays inside " + action.text)
            })
            checked++
          })
        })
      })
    })
    verify(checked >= 100, "bounded actual-control coverage")
    console.log("PANEL_ICONS " + checked + " action states; two locales/two widths")
    widget.liveState = {status:"paused", busy:true}
    compare(control("pauseButton").iconText, panel.glyphs.play)
    widget.liveState = {status:"playing", busy:true}
    compare(control("pauseButton").iconText, panel.glyphs.pause)
  }

  function test_icon_reacts_to_levels_start_pause_and_restart() {
    var icon = iconComponent.createObject(surface, {iconSize:16})
    verify(icon !== null)
    var bars = icon.children.filter(function(item) { return typeof item.index === "number" })
    compare(bars.length, 4)
    icon.levels = [.1, .8, .4, .2]
    wait(100)
    var resting = [4, 8, 6, 4]
    bars.forEach(function(bar, index) {
      fuzzyCompare(bar.height, resting[index], .01)
      compare(bar.level, 0)
      fuzzyCompare(bar.width, 1, .01)
      fuzzyCompare(bar.x, 8 + index * 2, .01)
      fuzzyCompare(bar.y + bar.height / 2, 8, .01)
    })
    icon.playing = true
    tryVerify(function() { return bars[1].height > 6 }, 200)
    wait(100)
    fuzzyCompare(bars[1].height, 8.3, .01)
    icon.levels = [.7, .1, .2, .9]
    tryVerify(function() { return bars[3].height > 7 && bars[1].height < 3 }, 200)
    icon.playing = false
    tryVerify(function() { return bars.every(function(bar, index) { return Math.abs(bar.height - resting[index]) < .01 }) }, 200)
    icon.levels = [.2, .3, .9, .1]
    icon.playing = true
    tryVerify(function() { return bars[2].height > 7 }, 200)
    var crown = findChild(icon, "monogramCrown")
    var shoulder = findChild(icon, "monogramShoulder")
    var stem = findChild(icon, "monogramStem")
    var foot = findChild(icon, "monogramFoot")
    verify(crown !== null && shoulder !== null && stem !== null && foot !== null)
    var strokes = [crown, shoulder, stem, foot]
    compare(crown.x, 1); compare(crown.y, 1); compare(crown.width, 6); compare(crown.height, 1)
    compare(shoulder.x, 0); compare(shoulder.y, 2); compare(shoulder.width, 8); compare(shoulder.height, 2)
    compare(stem.x, 3); compare(stem.y, 4); compare(stem.width, 3); compare(stem.height, 10)
    compare(foot.x, 3); compare(foot.y, 14); compare(foot.width, 2); compare(foot.height, 1)
    compare(foot.y + foot.height - crown.y, 14)
    fuzzyCompare(bars[0].x - stem.x - stem.width, 2, .01)
    icon.levels = [-1, 2, NaN, Infinity]
    wait(100)
    bars.forEach(function(bar) {
      verify(isFinite(bar.height) && bar.height >= 1.5 && bar.height <= 10)
      verify(bar.y >= 3 && bar.y + bar.height <= 13)
    })
    icon.levels = [1, 1, 1, 1]
    wait(100)
    bars.forEach(function(bar) { fuzzyCompare(bar.height, 10, .01) })
    icon.levels = [.25, .5, .75, 0]
    wait(100)
    bars.forEach(function(bar, index) { fuzzyCompare(bar.height, 1.5 + [.25, .5, .75, 0][index] * 8.5, .01) })
    icon.levels = null
    wait(100)
    bars.forEach(function(bar) { fuzzyCompare(bar.height, 1.5, .01) })
    icon.playing = false
    wait(100)
    bars.forEach(function(bar, index) {
      fuzzyCompare(bar.height, resting[index], .01)
      compare(bar.level, 0)
    })
    icon.color = "#345678"
    bars.forEach(function(bar) { compare(String(bar.color), "#345678") })
    strokes.forEach(function(stroke) { compare(String(stroke.color), "#345678") })
    var marker = findChild(icon, "busyMarker")
    verify(marker !== null)
    icon.busy = true
    verify(marker.visible)
    compare(marker.x, 13); compare(marker.y, 13); compare(marker.width, 2)
    icon.busy = false
    verify(!marker.visible)
    ;[24,32].forEach(function(size) {
      icon.iconSize = size
      bars.forEach(function(bar) {
        verify(bar.x >= 0 && bar.x + bar.width <= size)
        verify(bar.y >= 0 && bar.y + bar.height <= size)
      })
      fuzzyCompare(stem.width, size * 3 / 16, .01)
      fuzzyCompare(stem.height, size * 10 / 16, .01)
      strokes.forEach(function(stroke) {
        verify(stroke.x >= 0 && stroke.x + stroke.width <= size)
        verify(stroke.y >= 0 && stroke.y + stroke.height <= size)
      })
    })
    icon.destroy()
  }
}
