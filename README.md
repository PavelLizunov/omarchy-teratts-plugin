# TeraTTS for Omarchy

Read selected text, clipboard contents or a screen capture aloud through your
own [TeraTTS-compatible server](docs/SERVER.md). Save speech as MP3, OGG/Opus
or WAV, and preview your saved recordings from a native Omarchy panel.

[Releases](https://github.com/PavelLizunov/omarchy-teratts-plugin/releases)

Requires Linux, Omarchy Quattro and a compatible server. English and Russian
interface. This is a community plugin, not an official Omarchy component.

![Native Read panel with selection, clipboard, capture, voice and speed controls](docs/media/read-dark.png)

Screenshots and the [short demo](docs/media/demo.mp4) use the actual QML panel
with inert example data. The demo is silent; it does not demonstrate a live
server, screen capture or audio quality. [More previews and provenance](docs/media/README.md).

## Install

Review the source and dependencies first. The plugin runs unsandboxed with your
user permissions inside the shared Omarchy shell.

```sh
omarchy plugin add https://github.com/PavelLizunov/omarchy-teratts-plugin.git --enable
```

Open Settings, then Server. Enter your server's base HTTPS URL and token. A new
profile has no configured endpoint and makes no TTS request before setup.
Local HTTP is allowed only for localhost, 127.0.0.1 or ::1. No hosted account,
server, model weights or free service is bundled. A generic OpenAI or ElevenLabs
endpoint is not compatible unless it implements the documented TeraTTS protocol.

Do not enable this package and the predecessor Omarchy TTS together. They share
configuration, keyring accounts and playback state. This package retains the
stable ID io.github.pavellizunov.teratts; an existing install with that ID must
be updated or removed before adding this repository.

## Daily use

- Read: selection, clipboard, area/window/monitor OCR, voice and speech speed.
- Files: saved recordings, preview and seeking, explicit copy, confirmed deletion.
- Settings: voice test, optional OCR, independent server addresses and shortcuts.

Pause/Resume and Stop stay below scrolling content. The measured bar icon follows
this plugin's audio; idle and pause use a static silhouette, not a fake waveform.
Keyboard bindings are optional and installed explicitly in Settings, then Keys.
They are not installed by adding the repository. [Usage and shortcuts](docs/USAGE.md).

## Dependencies and data

Core commands: bash, jq, curl, Python 3.12 or newer, util-linux and mpv.
Selection and clipboard use wl-paste; capture uses grim and slurp. Encoded exports
need FFmpeg/ffprobe. File copy uses wl-copy, folder opening uses xdg-open, and
token storage uses secret-tool/libsecret. OCR is optional: Tesseract, pinned
EasyOCR, cloud APIs or a separately configured OCR server. [Setup details](docs/USAGE.md).

Speech text goes to your chosen server. Remote/cloud OCR receives images only
when used; local OCR stays local. Exported files are private XDG data. A valid
existing endpoint and recordings are preserved. No automatic clipboard paste,
messenger send or privileged package install occurs when adding the plugin.

## Update and remove

Stop active speech, preview or export before removal. If you installed shortcuts,
remove the owned binding block first; this does not touch unrelated bindings.

```sh
omarchy plugin update io.github.pavellizunov.teratts
# Before removing the plugin, only if its bindings were installed:
~/.config/omarchy/plugins/io.github.pavellizunov.teratts/bin/speak-bindings remove
omarchy plugin remove io.github.pavellizunov.teratts
```

Native removal deletes the plugin package, not configuration, keyring tokens,
optional OCR engines or saved recordings. It can reload shared plugin surfaces.
Close unsaved plugin forms first. [Storage, limits and full removal notes](docs/USAGE.md).

## Development and license

[Checks and known limits](docs/DEVELOPMENT.md) distinguish source, inert QML,
installed behavior and physical acceptance. Marketplace listing is not a
security certification. Report problems through this repository's issues.

MIT. Original copyright by Jesse Sanford retained. [Attribution](ATTRIBUTION.md).
