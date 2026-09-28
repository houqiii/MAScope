def content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(content_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            content_text(value[key])
            for key in (
                "instruction", "text", "content", "title", "evidence_id",
                "evidence_ids", "cited_identifiers", "inputs", "records",
                "carried_units", "attachments",
            )
            if key in value
        )
    return ""
