"""Обратная совместимость: Альфа-чек через patch_alfa_amount."""

from __future__ import annotations

from dataclasses import dataclass

from receipt_pdf_bot.receipt_alfa_patch import render_alfa_botpass_pdf


@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"


def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    return render_alfa_botpass_pdf({"amount": data.amount})
