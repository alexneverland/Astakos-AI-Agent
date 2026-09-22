# Spec: Immediate Photo Conversation Flow

## Objective

When the owner uploads a photo through Matrix or Telegram, Astakos immediately
uses the trusted vision analysis to reply naturally about the photo, then asks
exactly once whether it should be saved. The explicit yes/no confirmation is a
separate archive action, and later messages continue as ordinary conversation
with the photo context available in channel history.

## Commands

- Focused tests: `venv\Scripts\python.exe -m pytest tests/test_matrix_media_turn.py tests/test_matrix_turn.py tests/test_vision_image_migration.py -q --basetemp=<isolated-dir>`
- Diff validation: `git diff --check`

## Project Structure

- `services/pending_asset_confirmation.py`: shared localized photo-share request and archive-prompt normalization.
- `services/matrix_media_turn.py`: immediate Matrix photo-to-agent turn.
- `services/matrix_turn.py`: durable photo context and pending archive creation.
- `clients/telegram_bot.py`: immediate no-caption Telegram photo-to-agent turn.
- `locales/`: localized synthetic photo-share history text.
- `tests/`: offline regression coverage.

## Testing Strategy

- Mock all providers and transports; no live Matrix, Telegram, or AI calls.
- Prove a captionless photo immediately reaches the asset-aware turn.
- Prove the archive question appears exactly once and creates channel-local pending state.
- Prove later ordinary conversation retains the photo analysis through persisted model-only metadata.

## Boundaries

- Always: preserve explicit yes/no archive confirmation and untrusted-content provenance.
- Ask first: provider, credential, database schema, runtime, or watchdog changes.
- Never: auto-save a photo, expose provider metadata, or treat image analysis as user authorization.

## Success Criteria

- Captionless Matrix and Telegram photos receive an immediate natural reply.
- Matrix media captions behave like Telegram captions: ordinary text becomes the
  photo question, while exact `/nutrition` and `/receipt` captions run their
  existing photo tools.
- Every successful photo reply ends with one canonical save question.
- A pending photo archive exists before the user answers yes/no.
- Confirmed photos from every channel use the shared `PHOTOS_DIR` archive before
  the canonical Chroma and JSON indexes are written.
- The photo analysis remains available to later channel conversation.
- Nutrition/receipt commands and provider-error behavior remain unchanged.
