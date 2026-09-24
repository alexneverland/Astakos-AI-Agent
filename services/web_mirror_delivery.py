"""Drain display-only Web chat copies through the selected external transport."""

from __future__ import annotations

from hashlib import sha256

from config import CONVERSATION_DB_FILE
from core.i18n import t
from core.messaging_channel import ExternalChannel
from memory.conversation_history import (
    load_pending_web_mirrors,
    mark_web_mirror_delivered,
)
from services.external_delivery import (
    ExternalDeliveryError,
    ExternalDeliveryRouter,
    external_delivery_router,
)

# At most 24 KiB of UTF-8 text before Matrix encryption/event overhead.
_MATRIX_MIRROR_CHUNK_CHARS = 6000


def drain_web_mirrors(
    channel: ExternalChannel,
    *,
    router: ExternalDeliveryRouter = external_delivery_router,
    db_path: str = CONVERSATION_DB_FILE,
    limit: int = 20,
) -> int:
    """Deliver ordered pending copies; leave failures queued for a later run."""
    delivered = 0
    for item in load_pending_web_mirrors(channel, limit=limit, db_path=db_path):
        key = (
            "services.web_mirror_delivery.user_label"
            if item["role"] == "user"
            else "services.web_mirror_delivery.assistant_label"
        )
        text = f"{t(key)}\n{item['content']}"
        try:
            if channel == "matrix" and len(text) > _MATRIX_MIRROR_CHUNK_CHARS:
                for index, start in enumerate(range(0, len(text), _MATRIX_MIRROR_CHUNK_CHARS)):
                    chunk = text[start:start + _MATRIX_MIRROR_CHUNK_CHARS]
                    transaction_id = "astakos-web-mirror-" + sha256(
                        f"{item['message_id']}:{index}".encode("utf-8")
                    ).hexdigest()
                    receipt = router.send_matrix_mirror_chunk_to(
                        chunk, transaction_id=transaction_id
                    )
            else:
                receipt = router.send_text_to(channel, text, silent=True)
        except ExternalDeliveryError as exc:
            print(f"[WebMirror]: Delivery pending for {channel}: {exc}")
            break
        if not mark_web_mirror_delivered(
            item["message_id"], channel, receipt.external_id, db_path=db_path
        ):
            print(f"[WebMirror]: Acknowledgement failed for {item['message_id']}")
            break
        delivered += 1
    return delivered
