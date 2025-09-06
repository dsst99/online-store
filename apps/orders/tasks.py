import io
import logging
import time
from pathlib import Path

import requests
from celery import shared_task
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.orders.models import Order

logger = logging.getLogger(__name__)


def _pdf_path(order_id: int) -> Path:
    base = Path(getattr(settings, "MEDIA_ROOT", ".")) / "order_receipts"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"order_{order_id}.pdf"


@shared_task(
    name="orders.order_created_generate_pdf_and_email",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 5},
)
def order_created_generate_pdf_and_email(order_id: int) -> str:
    """
    Генерация PDF по заказу + имитация отправки email (лог).
    Возвращает путь к PDF.
    """
    order = Order.objects.select_related("user").prefetch_related("items__product").get(pk=order_id)

    # --- generate PDF in memory ---
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    text = c.beginText(40, 800)
    text.textLine(f"Order #{order.id}")
    text.textLine(f"User ID: {order.user_id}")
    text.textLine(f"Status: {order.status}")
    text.textLine(f"Total: {order.total_price}")
    text.textLine("")
    text.textLine("Items:")
    for item in order.items.all():
        text.textLine(
            f"- {item.product.name} x{item.quantity} @ {item.price_at_purchase} = "
            f"{item.quantity * item.price_at_purchase}"
        )
    c.drawText(text)
    c.showPage()
    c.save()

    # --- save to MEDIA_ROOT/order_receipts/order_<id>.pdf ---
    pdf_file = _pdf_path(order.id)
    pdf_file.write_bytes(buffer.getvalue())

    # --- simulate email send (log) ---
    logger.info("Order #%s PDF generated at %s; email sent to user %s", order.id, str(pdf_file), order.user_id)

    return str(pdf_file)


@shared_task(
    name="orders.order_shipped_notify_external",
    autoretry_for=(requests.RequestException, TimeoutError),
    retry_kwargs={"max_retries": 3, "countdown": 5},
    retry_backoff=True,
)
def order_shipped_notify_external(order_id: int) -> dict:
    """
    Имитация вызова внешнего API при статусе shipped.
    Ретраи при сетевых ошибках.
    """
    # небольшой «джиттер», чтобы показать ретраи в логах (необязательно)
    time.sleep(0.2)

    # пример: дергаем фейковый API
    url = "https://jsonplaceholder.typicode.com/posts"
    payload = {"title": f"order-{order_id}", "body": "shipped", "userId": 1}
    resp = requests.post(url, json=payload, timeout=5)
    resp.raise_for_status()
    data = resp.json()

    logger.info("Order #%s shipped notification sent. External id=%s", order_id, data.get("id"))
    return data
