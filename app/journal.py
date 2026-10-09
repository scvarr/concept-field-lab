"""Compact JSON history using RFC 6901 pointers and RFC 6902 add/remove/replace."""
import copy

from app.store import Invalid


def pointer(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def patch_between(before, after, path=""):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        patch = []
        for key in sorted(before.keys() - after.keys()):
            patch.append({"op": "remove", "path": path + "/" + pointer(key)})
        for key in sorted(after):
            child = path + "/" + pointer(key)
            if key not in before:
                patch.append({"op": "add", "path": child, "value": copy.deepcopy(after[key])})
            else:
                patch.extend(patch_between(before[key], after[key], child))
        return patch
    if isinstance(before, list) and isinstance(after, list):
        # Stable object IDs permit linear comparison without replacing entire large lists.
        if all(isinstance(item, dict) and isinstance(item.get("id"), (str, int)) for item in before + after):
            old = {item["id"]: item for item in before}
            new = {item["id"]: item for item in after}
            if len(old) == len(before) and len(new) == len(after):
                common_before = [item["id"] for item in before if item["id"] in new]
                common_after = [item["id"] for item in after if item["id"] in old]
                if common_before == common_after:
                    patch = [{"op": "remove", "path": path + "/" + str(i)} for i in range(len(before)-1, -1, -1) if before[i]["id"] not in new]
                    for i, item in enumerate(after):
                        child = path + "/" + str(i)
                        if item["id"] not in old:
                            patch.append({"op": "add", "path": child, "value": copy.deepcopy(item)})
                        else:
                            patch.extend(patch_between(old[item["id"]], item, child))
                    return patch
    return [{"op": "replace", "path": path, "value": copy.deepcopy(after)}]


def apply_patch(state, operations):
    result = copy.deepcopy(state)
    if not isinstance(operations, list):
        raise Invalid("История patch должна быть списком.")
    try:
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("op") not in ("add", "remove", "replace"):
                raise Invalid("История поддерживает add, remove и replace.")
            op, path = operation["op"], operation.get("path")
            if not isinstance(path, str) or (path and not path.startswith("/")):
                raise Invalid("Некорректный JSON Pointer.")
            if op != "remove" and "value" not in operation:
                raise Invalid("Отсутствует значение операции истории.")
            if not path:
                if op == "remove":
                    raise Invalid("Нельзя удалить всё состояние истории.")
                result = copy.deepcopy(operation["value"])
                continue
            keys = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
            parent = result
            for key in keys[:-1]:
                if isinstance(parent, list):
                    if not key.isdigit() or int(key) >= len(parent):
                        raise Invalid("Индекс истории вне диапазона.")
                    parent = parent[int(key)]
                else:
                    parent = parent[key]
            key = keys[-1]
            if isinstance(parent, list):
                index = len(parent) if key == "-" and op == "add" else int(key)
                if index < 0 or index > len(parent) or (op != "add" and index == len(parent)):
                    raise Invalid("Индекс истории вне диапазона.")
                if op == "add":
                    parent.insert(index, copy.deepcopy(operation["value"]))
                elif op == "remove":
                    parent.pop(index)
                else:
                    parent[index] = copy.deepcopy(operation["value"])
            elif isinstance(parent, dict):
                if op != "add" and key not in parent:
                    raise Invalid("Поле истории отсутствует.")
                if op == "remove":
                    del parent[key]
                else:
                    parent[key] = copy.deepcopy(operation["value"])
            else:
                raise Invalid("JSON Pointer проходит через скаляр.")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Invalid("Не удалось восстановить JSON историю: " + str(exc)) from exc
    return result


def compact_history(snapshots):
    return compact_with_latest(snapshots)[0]


def compact_with_latest(snapshots):
    history = []
    previous = {"studies": [], "matches": [], "imports": [], "proposals": []}
    for row in snapshots:
        history.append({k: v for k, v in row.items() if k != "state"} | {"patch": patch_between(previous, row["state"])})
        previous = row["state"]
    return history, previous


def expand_history(document):
    history = document.get("history", [])
    if not isinstance(history, list):
        raise Invalid("История должна быть списком.")
    previous = {"studies": [], "matches": [], "imports": [], "proposals": []}
    previous_id = -1
    for row in history:
        if not isinstance(row, dict) or not all(k in row for k in ("id", "time", "action", "detail")) or not isinstance(row["id"], int) or row["id"] <= previous_id:
            raise Invalid("Некорректная запись истории или порядок версий.")
        previous_id = row["id"]
        if "state" in row:
            previous = copy.deepcopy(row["state"])
        elif document.get("historyEncoding") == "rfc6902-chain-v1" and "patch" in row:
            previous = apply_patch(previous, row["patch"])
        else:
            raise Invalid("Неизвестная кодировка истории.")
        yield {**row, "state": previous}
