"""Extract public discussion text without executing page scripts or retaining hidden data."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

SOURCE = "https://chatgpt.com/share/6aca8be0-ef58-83eb-a4c4-b404468a46de"


def extract(html):
    marker = "streamController.enqueue("
    start = html.index(marker) + len(marker)
    payload, _ = json.JSONDecoder().raw_decode(html[start:])
    values = json.loads(payload)
    key_index = values.index("linear_conversation")
    owners = [v for v in values if isinstance(v, dict) and f"_{key_index}" in v]
    if len(owners) != 1:
        raise ValueError("Expected one linear conversation")
    cache = {}

    def resolve(index):
        if index < 0:
            return None
        if index in cache:
            return cache[index]
        value = values[index]
        if isinstance(value, dict):
            result = {}
            cache[index] = result
            result.update({values[int(k[1:])]: resolve(v) for k, v in value.items()})
        elif isinstance(value, list):
            result = []
            cache[index] = result
            result.extend(resolve(v) for v in value)
        else:
            result = value
            cache[index] = result
        return result

    nodes = resolve(owners[0][f"_{key_index}"])
    messages = []
    for node in nodes:
        message = node.get("message", {})
        role = message.get("author", {}).get("role")
        if role not in ("user", "assistant"):
            continue
        if message.get("metadata", {}).get("is_visually_hidden_from_conversation"):
            continue
        if message.get("channel") in ("analysis", "commentary", "justify", "confidence"):
            continue
        if message.get("recipient", "all") != "all":
            continue
        content = message.get("content", {})
        parts = content.get("parts", [])
        text = "\n\n".join(
            part if isinstance(part, str) else
            "[нетекстовое вложение: " + part.get("content_type", "unknown") + "]"
            for part in parts
        )
        if not text.strip():
            continue
        messages.append({"ref": f"S{len(messages) + 1:03}", "id": message["id"],
                         "role": role, "text": text,
                         "content_type": content.get("content_type")})
    if len({m["id"] for m in messages}) != len(messages):
        raise ValueError("Duplicate message IDs")
    title = re.search(r"<title>(.*?)</title>", html)
    return title.group(1) if title else None, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, help="Previously downloaded UTF-8 HTML")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-date", required=True)
    args = parser.parse_args()
    if args.html:
        raw = args.html.read_bytes()
    else:
        with urllib.request.urlopen(SOURCE, timeout=45) as response:
            raw = response.read()
    title, messages = extract(raw.decode("utf-8"))
    # Boundaries are specific to this shared-chat snapshot. Fail on changed history.
    if len(messages) != 131:
        raise ValueError(f"Expected 131 messages; got {len(messages)}. Review boundaries.")
    if "восстановление рабочего контекста" not in messages[0]["text"]:
        raise ValueError("Initial recovery text boundary changed")
    if "восстановительный промпт" not in messages[-2]["text"]:
        raise ValueError("Final recovery request boundary changed")
    if "Восстановление исследовательского контекста" not in messages[-1]["text"]:
        raise ValueError("Final recovery prompt boundary changed")
    included = messages[1:-2]
    snapshot = {
        "source_url": SOURCE, "title": title, "retrieved_date": args.retrieved_date,
        "retrieval": "HTTPS HTML; React Router linear_conversation, text-only projection",
        "html_sha256": hashlib.sha256(raw).hexdigest(),
        "numbered_messages_before_exclusion": len(messages),
        "excluded": [
            {"ref": "S001", "reason": "Начальный восстановительный текст"},
            {"ref": "S130", "reason": "Просьба подготовить восстановительный промпт"},
            {"ref": "S131", "reason": "Финальный восстановительный промпт"},
        ],
        "limitations": [
            "Служебные сообщения, вызовы инструментов и скрытые сообщения не сохраняются.",
            "Вложения заменены маркерами; пиксели изображений не извлекались.",
            "Встроенная разметка ответов сохранена как текст; интерактивные примеры не исполнялись.",
            "HTML не хранится: он содержит ненужные служебные данные; его hash относится к сеансу загрузки.",
        ],
        "messages": included,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"Saved {len(included)} messages: {included[0]['ref']}..{included[-1]['ref']}")


if __name__ == "__main__":
    main()
