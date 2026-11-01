"""Deliver queued Web-origin approvals from the active Matrix process."""

from __future__ import annotations

from core.approval import (
    build_approval_delivery_request,
    list_queued_matrix_approvals,
    record_pending_delivery,
)
from core.messaging_channel import resolve_external_channel
from services.external_delivery import (
    ExternalDeliveryError,
    ExternalDeliveryRouter,
    external_delivery_router,
)


def drain_queued_matrix_approvals(
    *, router: ExternalDeliveryRouter = external_delivery_router, limit: int = 20,
) -> int:
    """Send queued approvals only from the selected Matrix transport."""
    if resolve_external_channel() != "matrix":
        return 0
    delivered = 0
    for item in list_queued_matrix_approvals()[: max(1, min(limit, 100))]:
        call_id = item["tool_call_id"]
        request = build_approval_delivery_request({
            "id": call_id,
            "name": item["tool_name"],
            "args": item.get("tool_args", {}),
        })
        try:
            receipt = router.send_approval(request)
            record_pending_delivery(
                call_id,
                delivery_channel="matrix",
                external_message_id=receipt.external_id,
            )
        except (ExternalDeliveryError, KeyError, ValueError) as exc:
            print(f"[Matrix Approval]: Queued delivery pending ({type(exc).__name__})")
            break
        delivered += 1
    return delivered
