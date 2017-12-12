import re

import cchardet
import requests
from colorama import Fore
from selenium import webdriver

from toapi.cache import CacheSetting
from toapi.log import logger
from toapi.server import Server
from toapi.settings import Settings
from toapi.storage import Storage


class Api:
    """Api handle the routes dispatch"""

    def __init__(self, base_url=None, settings=None, *args, **kwargs):
        self.base_url = base_url
        self.settings = settings or Settings
        self.item_classes = []
        self.storage = Storage(settings=self.settings)
        self.cache = CacheSetting(settings=self.settings)
        self.server = Server(self, settings=self.settings)
        if getattr(self.settings, 'web_config', {}).get('with_ajax', False):
            self.browser = self.get_browser(settings=self.settings)
        else:
            self.browser = None
        self.web_config = getattr(self.settings, 'web_config', {})

    def register(self, item):
        """Register items"""
        item.__base_url__ = item.__base_url__ or self.base_url
        item.__pattern__ = re.compile(item.__base_url__ + item.Meta.route)
        self.item_classes.append(item)
        with_ajax = getattr(item.Meta, 'web_config', {}).get('with_ajax', False)
        if self.browser is None and with_ajax:
            self.browser = self.get_browser(settings=self.settings)

    def serve(self, ip='0.0.0.0', port=5000, **options):
        self.server.serve(ip, port, **options)

    def parse(self, path, params=None, **kwargs):
        """Parse items from a url"""

        all_items = {}
        for index, item in enumerate(self.item_classes):
            full_path = path[1:] if path.startswith('/http') else item.__base_url__ + path
            if item.__pattern__.match(full_path):
                all_items[full_path] = all_items.get(full_path, list())
                all_items[full_path].append(item)

        results = {}
        for url, items in all_items.items():
            for each_item in items:
                cached_item = self.get_cache(url)
                if cached_item is not None:
                    results.update(cached_item)
                else:
                    html = self.get_storage(url) or self.fetch_page_source(url, item=each_item, params=params, **kwargs)
                    if html is not None:
                        parsed_item = self.parse_item(html, each_item)
                        results.update(parsed_item)
                        self.set_cache(url, parsed_item)
        return results or None

    def fetch_page_source(self, url, item, params=None, **kwargs):
        """Fetch the html of given url"""
        self.update_status('_status_sent')
        if getattr(item.Meta, 'web_config', {}).get('with_ajax', False) or self.web_config.get('with_ajax', False):
            self.browser.get(url)
            text = self.browser.page_source
            if text != '':
                logger.info(Fore.GREEN, 'Sent', '%s %s 200' % (url, len(text)))
            else:
                logger.error('Sent', '%s %s' % (url, len(text)))
            result = text
        else:
            request_config = getattr(item.Meta, 'web_config', {}).get('request_config', {}) or self.web_config.get(
                'request_config', {})
            response = requests.get(url, params=params, **request_config)
            content = response.content
            charset = cchardet.detect(content)
            text = content.decode(charset['encoding'])
            if response.status_code != 200:
                logger.error('Sent', '%s %s %s' % (url, len(text), response.status_code))
            else:
                logger.info(Fore.GREEN, 'Sent', '%s %s %s' % (url, len(text), response.status_code))
            result = text
        self.set_storage(url, result)
        return result

    def get_browser(self, settings):
        if getattr(settings, 'headers', None) is not None:
            for key, value in settings.headers.items():
                capability_key = 'phantomjs.page.customHeaders.{}'.format(key)
                webdriver.DesiredCapabilities.PHANTOMJS[capability_key] = value
        phantom_options = []
        phantom_options.append('--load-images=false')
        return webdriver.PhantomJS(service_args=phantom_options)

    def update_status(self, key):
        """Set cache"""
        self.cache.set(key, str(self.get_status(key) + 1))

    def get_status(self, key):
        if self.cache.get(key) is None:
            self.cache.set(key, '0')
        return int(self.cache.get(key))

    def set_cache(self, key, value):
        """Set cache"""
        if self.cache.get(key) is None and self.cache.set(key, value):
            logger.info(Fore.YELLOW, 'Cache', 'Set<%s>' % key)
            self.update_status('_status_cache_set')
            return True
        return False

    def get_cache(self, key, default=None):
        """Set cache"""
        result = self.cache.get(key)
        if result is not None:
            logger.info(Fore.YELLOW, 'Cache', 'Get<%s>' % key)
            self.update_status('_status_cache_get')
            return result
        return default

    def set_storage(self, key, value):
        """Set storage"""
        if self.storage.get(key) is None and self.storage.save(key, value):
            logger.info(Fore.BLUE, 'Storage', 'Set<%s>' % key)
            self.update_status('_status_storage_set')
            return True
        return False

    def get_storage(self, key, default=None):
        """Set storage"""
        result = self.storage.get(key)
        if result is not None:
            logger.info(Fore.BLUE, 'Storage', 'Get<%s>' % key)
            self.update_status('_status_storage_get')
            return result
        return default

    def parse_item(self, html, item):
        """Parse item from html"""
        result = {}
        result[item.__name__] = item.parse(html)
        if len(result[item.__name__]) == 0:
            logger.error('Parsed', 'Item<%s[%s]>' % (item.__name__.title(), len(result[item.__name__])))
        else:
            logger.info(Fore.CYAN, 'Parsed', 'Item<%s[%s]>' % (item.__name__.title(), len(result[item.__name__])))
        return result
