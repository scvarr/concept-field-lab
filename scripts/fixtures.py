"""Synthetic fixtures only; no claims about the semantics of Russian words."""
import copy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.exchange import envelope

TIME = "2026-10-09T00:00:00+00:00"


def identity(key):
    return str(uuid5(NAMESPACE_URL, "concept-field-lab/synthetic/v1/" + key))


def make_node(key, label, kind="", notes=""):
    return {"id": identity(key), "label": label, "kind": kind, "notes": notes, "alternatives": "", "source": "Синтетические тестовые данные; не научный результат", "origins": [], "createdAt": TIME}


def make_study(key, title, nodes, edges):
    return {"id": identity(key), "title": title, "description": "Синтетический пример для проверки интерфейса и хранения. Содержание не подтверждено.", "rootId": nodes[0]["id"], "nodes": nodes, "edges": edges, "archived": False, "createdAt": TIME}


def make_edge(key, a, b, relation="раскрывается через"):
    return {"id": identity(key), "from": a, "to": b, "type": relation, "notes": "Тестовая связь", "origins": []}


def document(studies):
    state = {"studies": studies, "matches": [], "imports": [], "proposals": []}
    result = envelope("workspace", exportedAt=TIME, state=state, history=[{"id": 0, "time": TIME, "action": "synthetic-fixture", "detail": "Воспроизводимый тестовый материал; не научный результат", "state": copy.deepcopy(state)}])
    result["version"] = 1  # The legacy fixture stays byte-identical for compatibility checks.
    return result


def small():
    studies = []
    for key, word in (("a", "камень"), ("b", "камня")):
        nodes = [make_node(f"{key}/root", word, "слово"), make_node(f"{key}/spelling", word, "написание"), make_node(f"{key}/hard", "твёрдый", "свойство", f"Независимое синтетическое пояснение {key}"), make_node(f"{key}/definition", "сопротивление деформации", "определение"), make_node(f"{key}/alternative", "минерал" if key == "a" else "падежная форма", "интерпретация", "Альтернативы определяет оператор")]
        edges = [make_edge(f"{key}/e1", nodes[0]["id"], nodes[1]["id"], "записывается как"), make_edge(f"{key}/e2", nodes[0]["id"], nodes[2]["id"], "имеет свойство"), make_edge(f"{key}/e3", nodes[2]["id"], nodes[3]["id"]), make_edge(f"{key}/e4", nodes[3]["id"], nodes[0]["id"], "поясняется примером"), make_edge(f"{key}/e5", nodes[0]["id"], nodes[4]["id"], "альтернативная интерпретация")]
        studies.append(make_study(key, word, nodes, edges))
    return document(studies)


def large(size=5000):
    nodes = [make_node(f"large/n{i}", f"Элемент {i}", f"тип {i % 7}", f"Синтетическое содержание {i}") for i in range(size)]
    edges = []
    for i in range(size):
        edges.append(make_edge(f"large/next{i}", nodes[i]["id"], nodes[(i + 1) % size]["id"], "следующий"))
        edges.append(make_edge(f"large/reuse{i}", nodes[i]["id"], nodes[(i + 17) % size]["id"], "повторное использование"))
    return document([make_study("large", f"Масштабный тест: {size} элементов", nodes, edges)])


def large_composition(size=2000):
    alpha = make_node("large-composition/alpha", "")
    alpha["structure"] = "combination"
    nodes = [alpha] + [make_node(f"large-composition/c{i}", f"Компонент {i}") for i in range(size)]
    edges = [{**make_edge(f"large-composition/e{i}", alpha["id"], n["id"], ""), "role": "component"} for i, n in enumerate(nodes[1:])]
    result = document([make_study("large-composition/study", f"Комбинация: {size} компонентов", nodes, edges)])
    result["version"] = 2
    return result


def compositions():
    nodes = [make_node("composition/" + key, label) for key, label in (
        ("x", "X — синтетический пример"), ("word", "твёрдый"), ("hardness", "твёрдость"),
        ("modifier", "модификатор"), ("property", "свойство"), ("alpha", ""), ("beta", "β"), ("gamma", ""))]
    x, word, hardness, modifier, prop, alpha, beta, gamma = nodes
    for n in (alpha, beta, gamma):
        n["structure"] = "combination"
    edges = []
    for i, (a, b) in enumerate(((alpha, hardness), (alpha, modifier), (alpha, prop), (beta, alpha), (gamma, prop))):
        edge = make_edge(f"composition/c{i}", a["id"], b["id"], "")
        edge.update(role="component", componentRole="")
        edges.append(edge)
    for i, (a, b, relation) in enumerate(((x, alpha, "характеристика целого"), (x, beta, ""), (x, gamma, "другое утверждение"), (x, word, "свойство"))):
        edge = make_edge(f"composition/e{i}", a["id"], b["id"], relation)
        edge["role"] = "relation"
        edges.append(edge)
    study = make_study("composition/study", "Составные концепты — синтетический пример", nodes, edges)
    study["designations"] = [{"id": identity("composition/designation"), "text": "обозначение α", "target": alpha["id"], "notes": "Только тестовое обозначение", "source": "Синтетические данные", "origins": [], "createdAt": TIME}]
    result = document([study])
    result["version"] = 2
    return result


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "manual-example.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(small(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    target = target.with_name("composition-example.json")
    target.write_text(json.dumps(compositions(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
