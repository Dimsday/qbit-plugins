#VERSION: 0.15
#AUTHORS: Bugsbringer (dastins193@gmail.com)


EMAIL = "YOUR_EMAIL"
PASSWORD = "YOUR_PASSWORD"

ENABLE_PEERS_INFO = True


import concurrent.futures
import hashlib
import json
import os
import re
from collections import OrderedDict
from datetime import datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from io import BytesIO
from random import randint
from urllib import parse, request

from helpers import retrieve_url
from novaprinter import prettyPrinter


class lostfilm:
    url = 'https://www.lostfilm.tv'
    name = 'LostFilm'
    supported_categories = {'all': '0'}

    search_url_pattern = 'https://www.lostfilm.tv/search/?q={what}'
    serial_url_pattern = 'https://www.lostfilm.tv{href}/seasons'
    download_url_pattern = 'https://www.lostfilm.tv/v_search.php?a={code}'
    season_url_pattern = 'https://www.lostfilm.tv{href}/season_{season}'
    episode_url_pattern = 'https://www.lostfilm.tv{href}/season_{season}/episode_{episode}/'
    additional_url_pattern = 'https://www.lostfilm.tv{href}/additional/episode_{episode}/'
    new_url_pattern = "https://www.lostfilm.tv/new/page_{page}/type_{type}"

    additional_season = 999
    all_episodes = 999
    peer_id = None

    datetime_format = '%d.%m.%Y'

    def __init__(self):
        self.session = Session()

        if ENABLE_PEERS_INFO:
            self.peer_id = '-PC0001-' + ''.join([str(randint(0, 9)) for _ in range(12)])

    def pretty_log(self, data):
        prettyPrinter({
            'link': ' ',
            'name': str(data),
            'size': "0",
            'seeds': -1,
            'leech': -1,
            'engine_url': self.url,
            'desc_link': 'https://www.lostfilm.tv'
        })

    def search(self, what, cat='all'):
        if not self.session.is_actual:
            prettyPrinter({
                'link': ' ',
                'name': 'Error: {info}'.format(info=self.session.error),
                'size': "0",
                'seeds': -1,
                'leech': -1,
                'engine_url': self.url,
                'desc_link': 'https://www.lostfilm.tv/login'
            })

            return

        self.prevs = {}
        self.old_seasons = {}
        
        if parse.unquote(what).startswith('@'): 
            params = parse.unquote(what)[1:].split(':')
            
            if params:
                if params[0] == 'fav':
                    self.get_fav()

                elif params[0] == 'new':
                    if len(params) == 1:
                        self.get_new()

                    elif len(params) == 2 and params[1] == 'fav':
                        self.get_new(fav=True)

        else:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                for serial_href in self.get_serials(what):
                    executor.submit(self.get_episodes, serial_href)

    def get_new(self, fav=False, days=7):
        today = datetime.now().date()

        self.dates = {}

        page_number = 1

        with concurrent.futures.ThreadPoolExecutor() as executor:
            while True:
                opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
                params = parse.urlencode(self.session.cookies).encode('utf-8')
                url = self.new_url_pattern.format(page=page_number, type=99 if fav else 0)
                page = opener.open(url, params).read().decode('utf-8')

                rows = Parser(page).find_all('div', {'class': 'row'})

                if not rows:
                    break

                for row in rows:
                    
                    release_date_str = row.find_all('div', {'class': 'alpha'})[1].text
                    release_date_str = re.search(r'\d{2}.\d{2}.\d{4}', release_date_str)[0]
                    release_date = datetime.strptime(release_date_str, self.datetime_format).date()

                    delta = today - release_date

                    if delta.days > days:
                        return

                    href = '/'.join(row.a['href'].split('/')[:3])

                    haveseen_btn = row.find('div', {'onclick': 'markEpisodeAsWatched(this);'})
                    episode_code = haveseen_btn['data-episode'].rjust(9, '0')

                    self.dates[episode_code] = release_date_str
                    
                    executor.submit(self.get_torrents, href, episode_code, True)
                

                page_number += 1

    def get_fav(self):
        url = "https://www.lostfilm.tv/my/type_1"
        opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
        cookies = parse.urlencode(self.session.cookies).encode('utf-8')

        page = opener.open(url, cookies).read().decode('utf-8')

        with concurrent.futures.ThreadPoolExecutor() as executor:

            for serial in Parser(page).find_all('div', {'class': 'serial-box'}):
                href = serial.find('a', {'class': 'body'})['href']
                executor.submit(self.get_episodes, href)

    def get_serials(self, what):
        search_result = retrieve_url(self.search_url_pattern.format(what=request.quote(what)))

        serials_tags = Parser(search_result).find_all('div', {'class': 'row-search'})

        return [serial.a['href'] for serial in serials_tags]

    def get_episodes(self, serial_href):
        self.prevs[serial_href] = []
        self.old_seasons[serial_href] = 0

        serial_page = retrieve_url(self.serial_url_pattern.format(href=serial_href))
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for button in Parser(serial_page).find_all('div', {'class': 'external-btn'}):
                item_button = button.attrs.get('onclick')

                if item_button:
                    episode_code = re.search(r'\d{7,9}', item_button)[0].rjust(9, '0')
                    executor.submit(self.get_torrents, serial_href, episode_code)

    def get_torrents(self, href, code, new_episodes=False):
        season, episode = int(code[3:6]), int(code[6:])

        if not new_episodes:
            rules = [
                season > self.old_seasons[href],
                episode == self.all_episodes,
                season == self.additional_season
            ]

            if not any(rules):
                return

        opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
        params = parse.urlencode(self.session.cookies).encode('utf-8')
        url = self.download_url_pattern.format(code=code)
        redir_page = opener.open(url, params).read().decode('utf-8')

        torrent_page_url = re.search(r'(?<=location.replace\(").+(?="\);)', redir_page)

        if not torrent_page_url:
            return

        torrent_page = retrieve_url(torrent_page_url[0])
        desc_link = self.get_description_url(href, code)

        units_dict = {"ТБ": "TB", "ГБ": "GB", "МБ": "MB", "КБ": "KB"}

        torrent_dicts = []
        for torrent_tag in Parser(torrent_page).find_all('div', {'class': 'inner-box--item'}):
            main = torrent_tag.find('div', {'class': 'inner-box--link main'}).a
            link, name = main['href'], main.text.replace('\n', ' ')
            
            if not new_episodes:
                
                if link in self.prevs[href]:
                    # if this url alredy handled, then all episodes of this and older
                    # seasons will have torrent urls of episode's season instead of episode
                    self.old_seasons[href] = max(self.old_seasons[href], season)
                    break
                
                self.prevs[href].append(link)
            else:
                name = name + ' [' + self.dates[code] + ']'

            desc_box_text = torrent_tag.find('div', {'class': 'inner-box--desc'}).text
            size, unit = re.search(r'\d+.\d+ \w\w(?=\.)', desc_box_text)[0].split()

            torrent_dicts.append({
                'link': link,
                'name': name,
                'size': ' '.join((size, units_dict.get(unit, ''))),
                'seeds': -1,
                'leech': -1,
                'engine_url': self.url,
                'desc_link': desc_link
            })

        if ENABLE_PEERS_INFO:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                [prettyPrinter(tdict) for tdict in executor.map(self.get_torrent_info, torrent_dicts)]

        else:
            [prettyPrinter(tdict) for tdict in torrent_dicts]

    def get_description_url(self, href, code):
        season, episode = int(code[3:6]), int(code[6:])

        if season == self.additional_season:
            return self.additional_url_pattern.format(href=href, episode=episode)

        elif episode == self.all_episodes:
            return self.season_url_pattern.format(href=href, season=season)

        else:
            return self.episode_url_pattern.format(href=href, season=season, episode=episode)

    def get_torrent_info(self, tdict):
        try:
            req = request.Request(tdict['link'])

            torrent = bdecode(request.urlopen(req).read())
            info_hash = hashlib.sha1(bencode(torrent[b'info'])).digest()

            params = {
                'peer_id': self.peer_id,
                'info_hash': info_hash,
                'port': 6881,
                'left': 200075,
                'downloaded': 0,
                'uploaded': 0,
                'compact': 1
            }

            opener = request.build_opener()
            response = opener.open(torrent[b'announce'].decode('utf-8') + '?' + parse.urlencode(params))

            data = bdecode(response.read())

            tdict['seeds'] = data.get(b'complete', -1)
            tdict['leech'] = data.get(b'incomplete', 0) - 1
        except Exception as exp:
            if __name__ == '__main__':
                self.pretty_log(exp)

        return tdict


class Session:
    storage = os.path.abspath(os.path.dirname(__file__))
    file_name = 'lostfilm.json'
    datetime_format = '%m-%d-%y %H:%M:%S'

    token = None
    time = None
    error = None

    @property
    def file_path(self):
        return os.path.join(self.storage, self.file_name)

    @property
    def is_actual(self):
        """Needs to change session's token every 24 hours ot avoid captcha"""

        if self.token and self.time:
            delta = datetime.now() - self.time
            return delta.days < 1

        else:
            return False

    @property
    def cookies(self):
        if not self.is_actual:
            self.create_new()

        return {'lf_session': self.token}

    def __init__(self):
        self.load_data()

    def load_data(self):
        if not os.path.exists(self.file_path):
            self.create_new()
            self.save_data()

        else:
            with open(self.file_path, 'r') as file:
                result = json.load(file)

            if result.get('token') and result.get('time'):
                self.token = result['token']
                self.time = self.datetime_from_string(result['time'])

            if not self.is_actual:
                self.create_new()

    def create_new(self):
        if not EMAIL or not PASSWORD :
            self.error = 'Fill login data. {path}'.format(path=self.storage)

            return False

        login_data = {
            "act": "users",
            "type": "login",
            "mail": EMAIL,
            "pass": PASSWORD,
            "need_captcha": "",
            "captcha": "",
            "rem": 1
        }

        url = "https://www.lostfilm.tv/ajaxik.php?"
        
        cj = CookieJar()
        opener = request.build_opener(request.HTTPCookieProcessor(cj))
        params = parse.urlencode(login_data)
        response = opener.open(url, params.encode('utf-8'))
        
        result = json.loads(response.read().decode('utf-8'))
        
        if 'error' in result:
            self.error = result['error']

        elif 'need_captcha' in result:
            self.error = 'Captcha requested. Check description by right click.'

        else:
            for cookie in cj:
                if cookie.name == 'lf_session':
                    self.token = cookie.value
                    self.time = datetime.now()

                    self.save_data()

                    return True

            else:
                self.error = 'Token problem'
        
        return False

    def save_data(self):
        data = {
            "token": self.token,
            "time": None if not self.time else self.datetime_to_string(self.time)
        }

        with open(self.file_path, 'w') as file:
            json.dump(data, file)

    def datetime_to_string(self, dt_obj):
        if type(dt_obj) is datetime:
            return dt_obj.strftime(self.datetime_format)

        else:
            raise TypeError('argument must be datetime')

    def datetime_from_string(self, dt_string):
        if type(dt_string) is str:
            return datetime.strptime(dt_string, self.datetime_format)

        else:
            raise TypeError('argument must be str')


class Tag:
    def __init__(self, tag_type, *attrs):
        self.text = ''
        self.type = tag_type
        self.attrs = {attr: value for attr, value in attrs}
        self.tags = {}

    def _add_subtag(self, subtag):
        self.tags[subtag.type] = self.tags.get(subtag.type, []) + [subtag]

    def find(self, tag_type, attrs=None):
        result = self.find_all(tag_type, attrs)
        
        return None if not result else result[0]

    def find_all(self, tag_type, attrs=None):
        result = self.tags.get(tag_type)

        if attrs and result:
            def func(tag):
                if not set(attrs.keys()) <= set(tag.attrs.keys()):
                    return False

                for attr in attrs.keys():
                    if not set(attrs[attr].split()) <= set(tag.attrs[attr].split()):
                        return False
                
                return True

            result = list(filter(func, result))

        return result

    def __getitem__(self, key):
        return self.attrs[key]

    def __getattr__(self, tag):
        return self.find(tag)


class Parser(HTMLParser):

    @property
    def text(self):
        return self._root.text

    @property
    def attrs(self):
        return self._root.attrs

    def __init__(self, html_code, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._root = Tag('_root')
        self._current_path = [self._root]

        self.feed(html_code)

    def handle_starttag(self, tag, attrs):
        new = Tag(tag, *attrs)

        for tag in self._current_path:
            tag._add_subtag(new)

        self._current_path.append(new)

    def handle_endtag(self, tag):
        self._current_path.pop()

    def handle_startendtag(self, tag, attrs):
        new = Tag(tag, *attrs)
        for tag in self._current_path:
            tag._add_subtag(new)

    def handle_decl(self, decl):
        self._root._add_subtag(Tag('declaration'))

    def handle_data(self, data):
        for tag in self._current_path:
            tag.text += data

    def find(self, tag_type, attrs=None):
        return self._root.find(tag_type, attrs)

    def find_all(self, tag_type, attrs=None):
        return self._root.find_all(tag_type, attrs)

    def __getitem__(self, key):
        return self.attrs[key]

    def __getattr__(self, tag):
        return self.find(tag)


class InvalidBencode(Exception):
    @classmethod
    def at_position(cls, error, position):
        return cls("%s at position %i" % (error, position))

    @classmethod
    def eof(cls):
        return cls("EOF reached while parsing")


def bencode(value):
    if isinstance(value, dict):
        return b'd%be' % b''.join([bencode(k) + bencode(v) for k, v in value.items()])
    if isinstance(value, list) or isinstance(value, tuple):
        return b'l%be' % b''.join([bencode(v) for v in value])
    if isinstance(value, int):
        return b'i%ie' % value
    if isinstance(value, bytes):
        return b'%i:%b' % (len(value), value)

    raise ValueError("Only int, bytes, list or dict can be encoded, got %s" % type(value).__name__)


def bdecode(data):
    return decode_from_io(BytesIO(data))


def decode_from_io(f):
    char = f.read(1)
    if char == b'd':
        dict_ = OrderedDict()
        while True:
            position = f.tell()
            char = f.read(1)
            if char == b'e':
                return dict_
            if char == b'':
                raise InvalidBencode.eof()

            f.seek(position)
            key = decode_from_io(f)
            dict_[key] = decode_from_io(f)

    if char == b'l':
        list_ = []
        while True:
            position = f.tell()
            char = f.read(1)
            if char == b'e':
                return list_
            if char == b'':
                raise InvalidBencode.eof()
            f.seek(position)
            list_.append(decode_from_io(f))

    if char == b'i':
        digits = b''
        while True:
            char = f.read(1)
            if char == b'e':
                break
            if char == b'':
                raise InvalidBencode.eof()
            if not char.isdigit():
                raise InvalidBencode.at_position('Expected int, got %s' % str(char), f.tell())
            digits += char
        return int(digits)

    if char.isdigit():
        digits = char
        while True:
            char = f.read(1)
            if char == b':':
                break
            if char == b'':
                raise InvalidBencode
            digits += char
        length = int(digits)
        string = f.read(length)
        return string

    raise InvalidBencode.at_position('Unknown type : %s' % char, f.tell())


if __name__ == '__main__':
    import sys

    lostfilm().search(' '.join(sys.argv[1:]))
