"""Structural membership in the permanent graph, independent of relations."""
from app.store import Invalid


def validate_structure(nodes, edges, complete=True):
    indexed = {n['id']: n for n in nodes}
    children = {n['id']: [] for n in nodes}
    pairs = set()
    for edge in edges:
        role = edge.get('role', 'relation')
        if role not in ('relation', 'component'):
            raise Invalid('Функция ребра: relation или component.')
        if role != 'component':
            continue
        source, target = edge.get('from'), edge.get('to')
        if source not in indexed or target not in indexed:
            raise Invalid('Компонентность требует существующие ID.')
        node = indexed[source]
        base = node.get('base') if isinstance(node.get('base'), dict) else {}
        if node.get('structure', base.get('structure', 'concept')) != 'alpha':
            raise Invalid('Обязательный компонент может принадлежать только α.')
        if (source, target) in pairs:
            raise Invalid('Повтор обязательного компонента одной α.')
        pairs.add((source, target))
        children[source].append(target)
    # Iterative topological check avoids recursion limits on imported deep graphs.
    indegree = dict.fromkeys(indexed, 0)
    for targets in children.values():
        for target in targets:
            indegree[target] += 1
    pending = [key for key, degree in indegree.items() if degree == 0]
    count = 0
    while pending:
        source = pending.pop()
        count += 1
        for target in children[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    if count != len(indexed):
        raise Invalid('Цикл обязательного состава α не допускается.')
    if complete and any(n.get('structure') == 'alpha' and not children[n['id']] for n in nodes):
        raise Invalid('Опубликованная α требует хотя бы один обязательный компонент.')
