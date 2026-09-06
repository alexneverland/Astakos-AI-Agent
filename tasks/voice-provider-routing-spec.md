# Spec: Provider-Aware Voice

## Objective

Make Web and Telegram speech input/output use one explicitly resolved voice
provider. By default, voice follows the configured chat provider when that
provider supports both transcription and speech synthesis.

## Provider Contract

- `VOICE_PROVIDER=auto` selects the active chat provider only when it supports
  both `audio_stt` and `audio_tts`.
- Explicit values are `openai`, `gemini`, and `vertex`.
- OpenAI uses the configured OpenAI API key for transcription and TTS.
- Gemini uses the configured Gemini API key for transcription and Gemini TTS.
- Vertex uses the configured Google Cloud project credentials for transcription
  and Cloud Text-to-Speech.
- Anthropic has no implicit cross-provider fallback. An Anthropic chat setup
  must select one of the supported voice providers and configure its matching
  credential.

## Wake Name

- Live mode receives the trusted configured `voice_wake_name` from `/voice`.
- The default wake name is the configured bot name.
- Matching remains tolerant of a small transcription error but contains no
  hardcoded language-specific wake-word list.
- The transcription vocabulary hint uses the same configured wake name.

## Delivery Contract

- `/voice`, `/tts`, and Telegram voice handling use the same voice-provider
  resolver.
- TTS returns MP3 from every supported provider so browser playback and
  Telegram `sendVoice` keep the same transport contract.
- Missing or invalid voice configuration produces a clear setup-required error;
  it must never silently select an unrelated provider or drop a reply.

## Verification

- Offline adapter tests cover OpenAI, Gemini, and Vertex TTS boundaries.
- Resolver tests cover auto selection, an explicit secondary provider, and the
  Anthropic setup-required case.
- Web and Telegram tests prove that STT/TTS use the voice resolver.
- Setup tests prove that a separate voice credential is preserved and masked.
- Live UI tests cover configured Greek and English wake names plus a negative
  non-wake utterance without embedding either language in production code.

## Boundaries

- No live provider calls in tests.
- No modification of real `.env`, credential files, databases, Docker, or the
  watchdog.
- No realtime streaming-provider migration in this slice.
