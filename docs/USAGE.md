# Usage, setup and storage

## Panel and playback

Left-click the TeraTTS bar mark to open the panel. Right-click pauses/resumes
current playback or reads the selection when idle. Read contains selection,
clipboard, area/window/monitor capture, voice and speed. Capture closes the panel
before starting the owned cancellable command. Settings > Voice tests the phrase
through your server. Files opens the library first; Create file reveals export
source and format. Exporting does not play the resulting audio.

Pause/Resume, Stop and the effective cancellation shortcut remain outside page
scrolling. Preview speed is independent of the saved speech preference. Click
Copy only when you want a file URI in the clipboard; the plugin never pastes it.
Deletion uses an inline confirmation and stops the matching preview first.

## Optional shortcuts

Settings > Keys checks conflicts and installs only the marked omarchy-tts block
in your Hyprland bindings.lua. Existing unrelated bindings remain. Custom and
empty chords are supported. The footer advertises Stop only when verified active.
Defaults are Super+Alt+E selection/toggle, Super+Alt+A clipboard, Super+Alt+X Stop,
Super+Alt+R area, Super+Alt+W window, Super+Alt+Shift+R monitor and Super+Shift+L
library. Export and Pause have no default chord. Physical activation is host-owned.

Explicit CLI installation and removal:

```sh
~/.config/omarchy/plugins/io.github.pavellizunov.teratts/bin/speak-bindings install
~/.config/omarchy/plugins/io.github.pavellizunov.teratts/bin/speak-bindings remove
```

These commands edit the owned block and ask Hyprland to reload bindings. Use them
only when you intend that change. The plugin installer itself does not run them.

## OCR dependencies

Tesseract needs tesseract and its installed recognition-language packages. Refresh
and select languages in Settings > OCR. Unsupported/uninstalled languages fail
with guidance instead of downloading weights during recognition.

EasyOCR is optional. The shipped complete lock and model manifest pin dependency
and model digests. Explicit setup may install uv through Polkit/pacman, download
Python 3.12, synchronize packages and download model archives. It is not run on
plugin addition. The packaged English recognition model does not provide Russian
recognition; use Tesseract or an appropriate remote OCR server for that language.

```sh
~/.config/omarchy/plugins/io.github.pavellizunov.teratts/bin/speak-setup start easyocr
```

Do not interrupt an active setup transaction by removing the plugin. Google and
OpenAI OCR adapters use their respective accounts and send captures to those
providers. The dedicated OCR server is configured independently from TTS. No
cloud account, model or privileged optional installation is included by default.

## Data boundaries

The shared configuration is $XDG_CONFIG_HOME/omarchy-tts, normally
~/.config/omarchy-tts. Tokens live in the keyring, not exported audio metadata.
The package creates/migrates its own settings on CLI use while retaining valid
user values and unrelated retired fields. Invalid configuration is preserved
before normalization. New profiles have no TTS server address.

Recordings are under $XDG_DATA_HOME/omarchy-teratts/exports, normally
~/.local/share/omarchy-teratts/exports. Failed/cancelled jobs leave no published
library entry. Quotas are 20 files, 512 MiB total and 256 MiB per stored file;
existing files are not silently deleted to make room. TTS segments separately
have a 180-second audio bound. Local recognition engines and caches use the XDG
data/cache locations under omarchy-tts.

Native plugin removal leaves configuration, credentials, recordings and engines
in place. Removing those is separate user data cleanup. Disable conflicting TTS
widgets before enabling this one; predecessor and current plugin share stores.

## Troubleshooting

No configured server: set Settings > Server and follow SERVER.md. A bearer token
must be printable without whitespace; secret-tool requires an unlocked keyring.
Voice refresh failure: check /health compatibility and server reachability.
Generic API URLs and HTTP remote hosts are not accepted. Local files still remain
available even if the server is down. OCR language errors identify an engine/model
gap, not necessarily a server failure. A missing effective Stop chord should be
resolved in Settings > Keys; do not assume a default shortcut was installed.

The panel uses native theme typography and an internal scroll viewport. Report
persistent clipping with the page/state and display scale. Offscreen checks do
not establish every GPU/compositor, screen-reader or multimonitor condition.
