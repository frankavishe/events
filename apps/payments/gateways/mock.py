class MockGateway:
    """Accepts everything. Simulate the result by posting to the callback URL."""

    def checkout_mobile(self, *, payment_id, amount, phone, provider) -> str:
        return f"MOCK-{payment_id}"

    def checkout_bank(self, *, payment_id, amount, bank_name, account_number, phone, otp) -> str:
        return f"MOCK-{payment_id}"
