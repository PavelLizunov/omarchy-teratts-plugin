"""Static contracts for the installed TeraTTS panel."""
from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TeraPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (ROOT / "Panel.qml").read_text()
        cls.bar = (ROOT / "BarWidget.qml").read_text()
        cls.manifest = json.loads((ROOT / "manifest.json").read_text())
        cls.en = json.loads((ROOT / "locales/en.json").read_text())
        cls.ru = json.loads((ROOT / "locales/ru.json").read_text())

    def test_single_service_controls(self):
        for field in ('.teratts.voice', '.teratts.endpoint', '.rate', '--refresh-voices', '--stdin-json', '--stop'):
            self.assertIn(field, self.panel)
        for old_tab in ('FirstRunWizard', 'TtsController', 'KeyRow', 'Voice catalogue', 'Recognition engine'):
            self.assertNotIn(old_tab, self.panel)

    def test_private_text_and_token_channels(self):
        self.assertIn('write(JSON.stringify(root.pendingSpeech) + "\\n")', self.panel)
        self.assertIn('write(root.pendingKey + "\\n")', self.panel)
        self.assertRegex(self.panel, r'onVisibleChanged:\s*if \(!visible\)\s*text = ""')
        self.assertIn('keyField.text = ""', self.panel)
        self.assertIn('password: true', self.panel)

    def test_panel_lifecycle(self):
        self.assertIn('moduleName: "io.github.pavellizunov.teratts"', self.panel)
        self.assertIn('owner: root.barIdentity', self.panel)
        self.assertIn('Keys.onEscapePressed: root.cancelEditor()', self.panel)
        self.assertIn('Flickable {', self.panel)
        self.assertIn('ScrollBar.vertical: ScrollBar {', self.panel)
        self.assertIn('readonly property bool opened:', self.bar)

    def test_audio_panel_layout(self):
        self.assertEqual(self.manifest["barWidget"]["category"], "Audio")
        self.assertEqual(self.manifest["kinds"], ["bar-widget"])
        self.assertIn('fittedContentWidth(Style.space(380))', self.panel)
        self.assertIn('cappedContentHeight(Style.space(540))', self.panel)
        for page in ('read', 'audio', 'settings'):
            self.assertIn(f'root.panelPage === "{page}"', self.panel)
        for page in ('voice', 'screen', 'keys', 'server'):
            self.assertIn(f'root.settingsPage === "{page}"', self.panel)
        self.assertIn('id: footer', self.panel)
        self.assertIn('id: playbackControls', self.panel)
        self.assertNotIn('PanelHero {', self.panel)
        self.assertIn('WidgetButton {', self.bar)

    def test_internal_icons_supplement_identity_actions_and_text(self):
        self.assertIn("id: panelIcon", self.panel)
        self.assertIn("iconSize: Style.font.display", self.panel)
        self.assertIn("levels: root.playback.bands", self.panel)
        self.assertIn("component PanelHeading: Item", self.panel)
        self.assertIn("PanelSectionHeader {", self.panel)
        for key in ("selection", "clipboard", "stop", "play", "pause", "ocr", "copy", "remove", "server", "keys"):
            self.assertIn("root.glyphs." + key, self.panel)
        self.assertIn("iconText: root.glyphs[modelData.key]", self.panel)
        self.assertIn("iconText: root.glyphs[modelData.mode]", self.panel)
        self.assertIn("text: i18n.text(modelData.label)", self.panel)
        self.assertIn("Accessible.name: text", self.panel)
        self.assertIn("text: root.shortcutIcon(shortcutButton.modelData.key)", self.panel)

    def test_screen_capture_closes_panel_before_reading(self):
        for mode in ('snip', 'window', 'screen'):
            self.assertIn(f'mode:"{mode}"', self.panel)
        self.assertIn('root.readScreen(modelData.mode)', self.panel)
        self.assertRegex(self.panel, r'root.close\(\);?\s*ocrProc.command')
        self.assertIn('TTS_CAPTURE_DELAY: "0.25"', self.panel)
        self.assertNotIn('id: ocrLaunchTimer', self.panel)

    def test_remote_ocr_controls_use_separate_settings(self):
        self.assertIn('command: [root.speakBin, "--verify-ocr", "remote"]', self.panel)
        self.assertIn('root.setConfig(".ocr.remote.endpoint", text)', self.panel)
        self.assertIn('root.setConfig(".ocr.engine", value)', self.panel)
        self.assertIn('i18n.text("screen.remoteModelManaged")', self.panel)
        self.assertNotIn('.ocr.remote.model', self.panel)

    def test_shortcuts_use_existing_cli_and_catalogs(self):
        self.assertIn('command: [root.bindingsBin, "status"]', self.panel)
        self.assertIn('bindingWriteProc.command = [bindingsBin, "--locale", i18n.locale, "set", bindingAction, bindingDraft.trim()]', self.panel)
        self.assertEqual(set(self.en), set(self.ru))
        self.assertEqual(self.manifest["barWidget"]["defaults"]["locale"], "ru")
        self.assertIn('root.sampleText = result.ui?.sampleIsDefault === true', self.panel)
        self.assertIn('root.localPath("ru.json")', (ROOT / "I18n.qml").read_text())
        placeholder = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
        for key in self.en:
            self.assertEqual(set(placeholder.findall(self.en[key])),
                             set(placeholder.findall(self.ru[key])), key)
        for source in (self.panel, self.bar):
            self.assertNotRegex(source, r'"[^"\n]*[А-Яа-яЁё][^"\n]*"')

    def test_file_player_has_its_own_process_and_library_actions_stay_available(self):
        self.assertIn('id: audioPreviewProc', self.panel)
        self.assertIn('audioPreviewProc.command = [speakBin, "--audio-preview", id]', self.panel)
        self.assertNotIn('root.audioAction("--audio-preview"', self.panel)
        self.assertNotIn('enabled: !audioActionProc.running && !root.previewing', self.panel)
        self.assertIn('id: audioSeekSlider', self.panel)
        self.assertIn('"--playback-seek"', self.panel)
        self.assertIn('Qt.callLater(root.refreshAudio)', self.panel)
        self.assertIn('audioRow.activePreview ? root.pause()', self.panel)
        self.assertIn('root.readTextSource("selection")', self.panel)
        self.assertIn('root.readTextSource("clipboard")', self.panel)
        self.assertIn('command.indexOf("--stdin-json")', self.panel)
        self.assertIn('Qt.Key_End', self.panel)
        self.assertNotIn('Keys.onEndPressed', self.panel)
        self.assertNotIn('Keys.onHomePressed', self.panel)


if __name__ == "__main__":
    unittest.main()
