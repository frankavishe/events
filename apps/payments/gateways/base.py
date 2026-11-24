from decimal import Decimal
from typing import Protocol
from uuid import UUID


class PaymentGateway(Protocol):
    """Starts a payment; the result arrives later by callback.

    Both methods return the provider's transaction reference (or None) and raise
    `apps.common.exceptions.GatewayError` when the payment could not be started.
    """

    def checkout_mobile(
        self, *, payment_id: UUID, amount: Decimal, phone: str, provider: str
    ) -> str | None: ...

    def checkout_bank(
        self,
        *,
        payment_id: UUID,
        amount: Decimal,
        bank_name: str,
        account_number: str,
        phone: str,
        otp: str,
    ) -> str | None: ...
