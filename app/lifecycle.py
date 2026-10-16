"""Explicit cross-level deletion plans. No silent cascade; journal stays outside state."""
import copy
import hashlib
import json
from collections import Counter
from app.store import Invalid


def catalog(state):
    rows = {}

    def add(kind, value, label, deps=()):
        key = kind + ':' + value['id']
        rows[key] = {'key': key, 'kind': kind, 'id': value['id'], 'label': label, 'depends': set(deps)}

    for n in state['nodes']:
        words = [d['text'] for d in state['designations'] if d['target'] == n['id']]
        add('node', n, n.get('operatorAlias') or ', '.join(words) or n['id'])
    for e in state['edges']:
        add('edge', e, f'{e["from"]} → {e["to"]}', ['node:' + e[k] for k in ('from', 'to')])
    for c in state['contextEdges']:
        add('context', c, f'{c["from"]} ⇒ {c["to"]}', ['edge:' + c[k] for k in ('from', 'to')])
    for d in state['designations']:
        add('designation', d, d['text'], ['node:' + d['target']])
    for d in state['definitionDrafts']:
        p = state['definitionPublications'].get(d['id'], {})
        deps = ['node:' + i for i in p.get('nodeIds', [])]
        deps += ['edge:' + i for i in p.get('edgeIds', []) + p.get('componentIds', [])]
        deps += ['context:' + i for i in p.get('contextIds', [])]
        for k, kind in [('nodes', 'node'), ('edges', 'edge'), ('contextEdges', 'context')]:
            deps += [kind + ':' + v['id'] for v in d[k] if kind + ':' + v['id'] in rows]
        add('definition', d, d['title'], deps)

    def config_refs(c):
        return (['node:' + n['conceptId'] for n in c.get('nodes', [])]
                + ['node:' + n['contentConceptId'] for n in c.get('nodes', []) if n.get('contentConceptId')]
                + ['edge:' + e['edgeId'] for e in c.get('edges', [])]
                + ['context:' + p['contextId'] for p in c.get('contexts', [])])

    lab = state.get('thoughtLab', {})
    for t in lab.get('templates', []):
        add('template', t, t['label'], config_refs(t['config']))
    for c in lab.get('candidates', []):
        deps = ['edge:' + c[k] for k in ('from', 'to')]
        if c['status'] == 'accepted':
            deps += ['context:' + p['id'] for p in state['contextEdges'] if p['from'] == c['from'] and p['to'] == c['to']]
        add('candidate', c, c['reason'], deps)
    scenes = state.get('sceneLab', {})
    facts = {f['id']: e['id'] for s in scenes.get('scenes', []) for e in s['entries'] for f in e['assertions']}
    for s in scenes.get('scenes', []):
        add('scene', s, s['label'])
        for target in s['links']:
            add('link', {'id': s['id'] + '/' + target}, 'Ссылка сцены ' + s['label'], ['scene:' + s['id'], 'scene:' + target])
        for o in s['objects']:
            add('object', o, o['label'], ['scene:' + s['id'], 'node:' + o['conceptId']]
                + (['node:' + o['contentConceptId']] if o.get('contentConceptId') else []))
        for e in s['entries']:
            deps = ['scene:' + s['id']]
            for f in e['assertions']:
                deps += ['edge:' + f['edgeId'], 'object:' + f['from'], 'object:' + f['to']]
            deps += ['entry:' + facts[i] for i in e['retracts']]
            if e.get('contextSceneId'):
                deps += ['scene:' + e['contextSceneId'], 'link:' + s['id'] + '/' + e['contextSceneId']]
            if e.get('thoughtId'):
                deps += ['thought:' + e['thoughtId']]
            add('entry', e, e['text'], deps)
    for w in scenes.get('workspaces', []):
        deps = ['scene:' + w['sceneId']]
        for b in w['bundles']:
            deps += ['scene:' + b['sourceSceneId']]
            deps += ['entry:' + f['origin']['entryId'] for f in b['assertions']]
            deps += ['object:' + o['sourceObjectId'] for o in b['objects']]
        add('workspace', w, w['label'], deps)
    for d in lab.get('drafts', []):
        deps = config_refs(d['config']) + config_refs(d.get('contract') or {})
        deps += config_refs(d.get('templateArchive', {}).get('config', {}))
        if d.get('sceneId'):
            deps += ['scene:' + d['sceneId']]
        if d.get('entryId'):
            deps += ['entry:' + d['entryId']]
        deps += ['object:' + n['sceneObjectId'] for n in d['config']['nodes'] if n.get('sceneObjectId')]
        deps += ['object:' + b['objectId'] for b in d.get('objectBindings', [])]
        add('thought', d, ('Черновик: ' if d['status'] == 'draft' else 'Мысль: ') + d['text'], deps)
    return rows


def prepare(state, data, revision):
    from app.permanent import empty_graph, validate_graph
    rows = catalog(state)
    mode = data.get('mode', 'delete')
    if mode not in ('delete', 'reset'):
        raise Invalid('Удаление записей или полный сброс состояния.')
    selection = data.get('selection', [])
    if not isinstance(selection, list) or any(not isinstance(k, str) for k in selection) or len(selection) != len(set(selection)):
        raise Invalid('Нужен список различных ключей записей.')
    selected = set(rows) if mode == 'reset' else set(selection)
    if not selected <= rows.keys() or (not selected and mode != 'reset'):
        raise Invalid('Выберите существующие записи для удаления.')
    closure = set(selected)
    while True:
        expanded = closure | {k for k, v in rows.items() if v['depends'] & closure}
        # Removing the last mandatory component would invalidate an alpha.
        # Other component removals are allowed without deleting the whole alpha.
        for n in state['nodes']:
            if n['structure'] == 'alpha':
                components = [e for e in state['edges'] if e['role'] == 'component' and e['from'] == n['id']]
                if components and all('edge:' + e['id'] in expanded for e in components):
                    expanded.add('node:' + n['id'])
                    rows['node:' + n['id']]['depends'].update('edge:' + e['id'] for e in components)
        if expanded == closure:
            break
        closure = expanded
    blocked = closure - selected
    result = copy.deepcopy(state)
    rewrites = []
    if mode == 'reset':
        result = {**empty_graph(), 'operatorVersion': 5}
    elif not blocked:
        result['operatorVersion'] = 5
        mapping = {'nodes': 'node', 'edges': 'edge', 'contextEdges': 'context', 'designations': 'designation', 'definitionDrafts': 'definition'}
        removed_definitions = {d['id']: copy.deepcopy(d) for d in result['definitionDrafts'] if 'definition:' + d['id'] in selected}
        for collection, kind in mapping.items():
            result[collection] = [v for v in result[collection] if kind + ':' + v['id'] not in selected]
        for ident in removed_definitions:
            result['definitionPublications'].pop(ident, None)
        for k in ('nodes', 'edges', 'contextEdges', 'designations'):
            for value in result[k]:
                if value.get('definitionId') in removed_definitions:
                    archived = removed_definitions[value.pop('definitionId')]
                    value.setdefault('origins', []).append({'operation': 'archive_definition', 'definitionId': archived['id'],
                        'snapshot': {'title': archived['title'], 'definition': archived['definition']}})
                    rewrites.append({'kind': k, 'id': value['id'], 'change': 'Происхождение определения сохранено снимком'})
        if 'thoughtLab' in result:
            lab = result['thoughtLab']
            removed_templates = {t['id']: t for t in lab['templates'] if 'template:' + t['id'] in selected}
            removed_thoughts = {d['id']: d for d in lab['drafts'] if 'thought:' + d['id'] in selected}
            for key, kind in [('drafts', 'thought'), ('templates', 'template'), ('candidates', 'candidate')]:
                lab[key] = [v for v in lab[key] if kind + ':' + v['id'] not in selected]
            for d in lab['drafts']:
                ident = (d.get('templateRef') or {}).get('id')
                if ident in removed_templates:
                    d['templateArchive'] = copy.deepcopy(removed_templates[ident])
                    # The application contract remains pinned to its original version.
                    d['templateArchive']['version'] = d['templateRef']['version']
                    d['templateArchive']['config'] = copy.deepcopy(d.get('contract') or d['templateArchive']['config'])
                    rewrites.append({'kind': 'thought', 'id': d['id'], 'change': 'Шаблон сохранён внутри прежнего применения'})
            if 'thought:' + str(lab['currentDraftId']) in selected:
                lab['currentDraftId'] = None
        else:
            removed_thoughts = {}
        if 'sceneLab' in result:
            lab = result['sceneLab']
            lab['scenes'] = [s for s in lab['scenes'] if 'scene:' + s['id'] not in selected]
            for s in lab['scenes']:
                s['links'] = [i for i in s['links'] if 'link:' + s['id'] + '/' + i not in selected]
                s['entries'] = [e for e in s['entries'] if 'entry:' + e['id'] not in selected]
                s['objects'] = [o for o in s['objects'] if 'object:' + o['id'] not in selected]
                for o in s['objects']:
                    if o.get('thoughtId') in removed_thoughts:
                        origin = removed_thoughts[o.pop('thoughtId')]
                        o['originThought'] = {'id': origin['id'], 'text': origin['text'], 'localId': o.pop('localId', None)}
                        rewrites.append({'kind': 'object', 'id': o['id'], 'change': 'Происхождение удалённой мысли сохранено снимком'})
            lab['workspaces'] = [w for w in lab['workspaces'] if 'workspace:' + w['id'] not in selected]
            if 'scene:' + str(lab['currentSceneId']) in selected:
                lab['currentSceneId'] = None
        validate_graph(result)
    public = lambda keys: [{k: v for k, v in rows[key].items() if k != 'depends'} for key in sorted(keys)]
    removable = set()
    for s in state.get('sceneLab', {}).get('scenes', []):
        for o in s['objects']:
            key = 'object:' + o['id']
            if ('thought:' + str(o.get('thoughtId')) in closure and key not in closure
                    and not any(key in v['depends'] for k, v in rows.items() if k not in closure)):
                removable.add(key)
    preview = {'revision': revision, 'mode': mode, 'selected': public(selected), 'blocked': public(blocked), 'optional': public(removable),
               'counts': dict(Counter(rows[k]['kind'] for k in selected)), 'rewrites': rewrites,
               'dependencies': {k: sorted(rows[k]['depends'] & closure) for k in sorted(closure)}}
    preview['hash'] = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result, preview
