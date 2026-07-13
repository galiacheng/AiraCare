"""Voice subpackage: local TTS / ASR / VAD and the LocalVoiceService.

All heavy audio/ML imports are lazy (inside functions), so importing this package does
not require the ``[audio]`` extra. Only constructing/using the concrete backends pulls
them in.
"""
