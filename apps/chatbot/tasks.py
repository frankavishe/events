from celery import shared_task

from . import services
from .models import ChatMessage


@shared_task
def process_message(message_id):
    message = ChatMessage.objects.filter(pk=message_id).first()
    if message:
        services.process_conversation(message.conversation_id)


@shared_task
def process_conversation(conversation_id):
    services.process_conversation(conversation_id)


@shared_task
def resume_stuck_messages() -> int:
    """Pick up messages whose task was lost, failed to send, or died half way."""
    stuck = services.stuck_conversations()
    for conversation_id in stuck:
        process_conversation.delay(str(conversation_id))
    return len(stuck)
