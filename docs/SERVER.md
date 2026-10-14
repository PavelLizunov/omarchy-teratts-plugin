# Bring your own TeraTTS endpoint

The base URL belongs to the user. Set it in Settings > Server, or explicitly:

```sh
~/.config/omarchy/plugins/io.github.pavellizunov.teratts/bin/speak --set .teratts.endpoint https://tts.example.com
```

The example is not a hosted service. Use your own HTTPS origin, optionally with
a port. URLs with a path, query, embedded credentials or redirect are not supported.
HTTP is accepted only for local loopback hosts. The separate server project is
[TeraTTS server](https://github.com/PavelLizunov/teratts-server).

A compatible implementation provides the following contract.

## Voice discovery

GET /health returns a bounded JSON object. The voice refresh expects voices as
an array of string identifiers. A readiness probe expects status equal to ready.

```json
{"status":"ready","sample_rate":44100,"voices":["ru_f1","ru_m1","eng_f3"]}
```

Health requests currently do not include the TTS bearer token. Put authentication
on synthesis; a server that protects /health may prevent discovery/readiness.
A built-in voice list is the offline fallback. Supported configured voices are
ru_f1, ru_f2, ru_m1, ru_m5, eng_f3, eng_f4_whisper, eng_f5, eng_m2_whisper,
eng_m3 and eng_m4. This is not a generic arbitrary-voice API adapter.

## Synthesis

POST /tts accepts application/json. The panel/CLI provider requires a bearer
token, resolved from TERATTS_BEARER_TOKEN first, then the system keyring's
omarchy-tts/teratts account. Tokens are 8 to 4096 printable non-whitespace ASCII
characters. Enter/store a token in the panel; do not put credentials in the URL.
A tokenless local server is not a supported panel configuration. The underlying
synthesis library can omit Authorization, but the provider does not expose that
as a user option.

```json
{
  "text":"A sentence to read.",
  "voice":"eng_f3",
  "language":"en",
  "duration_scale":1.0,
  "speech_front":true,
  "text_mode":"compatible"
}
```

The example uses an English voice. English synthesis sends text_mode=compatible;
Russian voices default to russian_only. Ordinary speech sends duration_scale=1
and changes speed locally. Export passes the inverse of the selected speech rate.

The response is a complete RIFF/WAVE PCM payload: mono, signed 16-bit, 44100 Hz,
not MP3, SSE or a JSON audio URL. Each segment is bounded by character, byte and
180-second audio limits. HTTP redirects are rejected. Pause/speed/seek operate
in the plugin's mpv player; exported speech passes duration_scale to the server.

A third-party endpoint works only if it follows this contract. The package does
not provide an OpenAI-compatible /v1/audio/speech adapter or automatically change
providers. Three fresh-profile tests verify no request before setup, preserved
configuration and export to two independent finite loopback fixtures. They do
not certify an arbitrary remote server, pronunciation or credentials.

## Optional OCR server

OCR has its own address in Settings > Server and no implicit TTS endpoint reuse.
GET /healthz returns status=ok and ocr=ready. POST /v1/ocr accepts a multipart
file field containing PNG or JPEG and returns a JSON object with text. This
adapter has no bearer-token field. Use local OCR or a trusted accessible endpoint
with the documented protocol; do not assume compatibility with a generic image API.
