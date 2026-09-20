"""The voice container: transcription and synthesis, on CPU, from local files.

M6-AUDIO-DEPLOY-125. Scope stops at model loading and health — the WebSocket
audio path is `M6-AUDIO-API-126`. See `docs/architecture.md` §2.1 and
`docs/decisions.md` for why this stays a container rather than a second
native process.
"""
