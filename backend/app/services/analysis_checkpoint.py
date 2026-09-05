"""Reuse completed file analyses after worker interruption; commit files atomically."""

import asyncio
import hashlib
import json
import os
from app.services.audit_queue import workspace_for


async def analyze_file(
    task_id,
    file_path,
    content,
    service,
    language,
    *,
    rule_set_id=None,
    prompt_template_id=None,
    db=None,
):
    key = hashlib.sha256((file_path + "\0" + content).encode()).hexdigest()
    cache = workspace_for(task_id) / "analysis" / f"{key}.json"
    if cache.exists():
        try:
            return json.loads(await asyncio.to_thread(cache.read_text))
        except (ValueError, OSError):
            pass
    if rule_set_id or prompt_template_id:
        result = await service.analyze_code_with_rules(
            content,
            language,
            rule_set_id=rule_set_id,
            prompt_template_id=prompt_template_id,
            db_session=db,
        )
    else:
        result = await service.analyze_code(content, language)

    def persist():
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(result, output, ensure_ascii=False)
        os.replace(temporary, cache)

    await asyncio.to_thread(persist)
    return result
