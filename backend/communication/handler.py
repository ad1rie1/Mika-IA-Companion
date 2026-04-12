"""Unified message handler — entry point for all communication channels."""


async def handle_message(
    message: str,
    source: str = "frontend",
    person_id: str = "anonymous",
):
    """Process an incoming message from any communication channel via the pipeline."""
    from pipeline.processor import process_message

    output = await process_message(
        message=message,
        source=source,
        person_id=person_id,
    )
    return output.text, output.emotion_data
