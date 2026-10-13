"""Read Russian Wiktionary senses, with an explicit local cache and no graph writes."""
import hashlib
import json
import os
import ssl
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from app.store import clean, now

LICENSE = 'CC BY-SA 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/'
USER_AGENT = 'ConceptFieldLab/0.1 (https://github.com/scvarr/concept-field-lab; manual dictionary research)'
MAX_BYTES = 2 * 1024 * 1024


class SensesParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.russian = False
        self.meanings = False
        self.heading = None
        self.heading_text = []
        self.entry = ''
        self.language_level = None
        self.depth = 0
        self.text = []
        self.senses = []

    def handle_starttag(self, tag, attrs):
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5'):
            self.heading = tag
            self.heading_text = []
            self.meanings = False
        if self.russian and self.meanings and tag == 'li':
            if not self.depth:
                self.text = []
            self.depth += 1
        if self.depth and tag in ('br', 'p'):
            self.text.append(' ')

    def handle_data(self, data):
        if self.heading:
            self.heading_text.append(data)
        if self.depth:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading:
            value = ''.join(self.heading_text).strip()
            if value == 'Русский':
                self.russian = True
                self.language_level = tag
                self.entry = ''
            elif tag == self.language_level:
                self.russian = False
            elif self.russian and tag in ('h2', 'h3') and not any(t in value for t in ('свойства', 'Произношение', 'Этимология', 'слова', 'Перевод', 'Библиография', 'сочетания')):
                self.entry = value
            self.meanings = self.russian and value == 'Значение'
            self.heading = None
        if self.depth and tag == 'li':
            self.depth -= 1
            if not self.depth:
                text = ' '.join(''.join(self.text).split()).split('◆', 1)[0].strip()
                if text and text != 'Отсутствует пример употребления (см. рекомендации).':
                    self.senses.append({'entry': self.entry, 'text': text})


def fetch_json(url):
    request = Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urlopen(request, timeout=8) as response:
            payload = response.read(MAX_BYTES + 1)
    except URLError as exc:
        # On Windows, use the OS TLS stack if Python's separate CA chain fails.
        # Certificate verification remains enabled; there is no insecure retry.
        if os.name != 'nt' or not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        result = subprocess.run(['curl.exe', '--fail', '--silent', '--show-error', '--max-time', '10',
            '--max-filesize', str(MAX_BYTES), '--user-agent', USER_AGENT, url],
            capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise OSError('Системный HTTPS-клиент не смог получить толкования.')
        payload = result.stdout
    if len(payload) > MAX_BYTES:
        raise ValueError('Ответ словаря превышает 2 МиБ.')
    return json.loads(payload.decode('utf-8'))


class Definitions:
    def __init__(self, cache_dir, fetcher=fetch_json):
        self.directory = Path(cache_dir)
        self.fetcher = fetcher
        self.lock = threading.Lock()

    def get(self, lemma, refresh=False):
        lemma = clean(lemma, 'лемма', True, 100)
        target = self.directory / (hashlib.sha256(lemma.casefold().encode()).hexdigest() + '.json')
        with self.lock:
            cached = None
            if target.exists():
                try:
                    cached = json.loads(target.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
            if cached and not refresh:
                return {**cached, 'status': 'cache', 'message': 'Сохранённые толкования; можно обновить из сети.'}
            try:
                api = 'https://ru.wiktionary.org/w/api.php?' + urlencode({'action': 'parse', 'format': 'json', 'formatversion': 2,
                    'page': lemma, 'prop': 'text|revid', 'redirects': 1})
                result = self.fetcher(api)
                if result.get('error'):
                    code = result['error'].get('code')
                    if code == 'missingtitle':
                        return {'lemma': lemma, 'senses': [], 'status': 'missing', 'message': 'Статья не найдена. Введите собственный текст.'}
                    raise ValueError('Ошибка словарного API.')
                page = result['parse']
                parser = SensesParser()
                parser.feed(page['text'])
                source = {'name': 'Русский Викисловарь', 'url': 'https://ru.wiktionary.org/wiki/' + quote(page['title']),
                    'revision': page['revid'], 'revisionUrl': 'https://ru.wiktionary.org/w/index.php?oldid=' + str(page['revid']),
                    'retrievedAt': now(), 'license': LICENSE, 'licenseUrl': LICENSE_URL,
                    'attribution': 'Участники Викисловаря', 'transformation': 'Russian Значение sections, plain text before usage examples; no semantic decomposition',
                    'responseSha256': hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
                senses = [{**s, 'id': str(i + 1), 'source': source} for i, s in enumerate(parser.senses[:60])]
                data = {'lemma': lemma, 'senses': senses, 'source': source}
                if senses:
                    try:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_suffix('.tmp')
                        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8', newline='\n')
                        temporary.replace(target)
                    except OSError:
                        return {**data, 'status': 'online', 'message': 'Получено из сети; локальный кэш не записан.'}
                return {**data, 'status': 'online' if senses else 'missing', 'message': 'Толкования из Викисловаря.' if senses else 'Русские значения не найдены. Введите свой текст.'}
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                if cached:
                    return {**cached, 'status': 'offline-cache', 'message': 'Сеть недоступна; показаны сохранённые толкования.'}
                return {'lemma': lemma, 'senses': [], 'status': 'unavailable', 'message': 'Не удалось получить толкования. Можно работать с локальными формами и собственным текстом.'}
