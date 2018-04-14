# coding: utf-8
"""Iterators over Instagram media pages.
"""
from __future__ import absolute_import
from __future__ import unicode_literals

import abc
import hashlib
import math
import time
import typing

import six
from requests import Session

from ._impl import json
from ._utils import get_shared_data

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterator, Iterable, Optional, Text


__all__ = [
    "PageIterator",
    "HashtagIterator",
    "ProfileIterator",
]


@six.add_metaclass(abc.ABCMeta)
class PageIterator(typing.Iterator[typing.Dict[typing.Text, typing.Any]]):
    """An abstract Instagram page iterator.
    """

    BASE_URL = "https://www.instagram.com/graphql/query/"
    PAGE_SIZE = 200
    INTERVAL = 0.5

    section_generic = NotImplemented    # type: Text
    section_media = NotImplemented      # type: Text

    def __init__(self, session, rhx):
        # type: (Session) -> None
        self._session = session
        self.rhx = rhx
        self._finished = False
        self._cursor = None     # type: Optional[Text]
        self._current_page = 0
        self._total = None      # type: Optional[int]
        self._done = 0
        self._data_it = iter(self._page_loader(self._session))

    @abc.abstractmethod
    def _getparams(self, cursor):
        # type: (Optional[Text]) -> Text
        return NotImplemented

    def _page_loader(self, session):
        # type: (Session) -> Iterable[Dict[Text, Dict[Text, Any]]]
        while True:
            try:

                params = self._getparams(self._cursor)
                json_params = json.dumps(params, separators=(',', ':'))
                magic = "{}:{}:{}".format(self.rhx, session.headers['X-CSRFToken'], json_params)
                session.headers['x-instagram-gis'] = hashlib.md5(magic.encode('utf-8')).hexdigest()
                url = self.URL.format(json_params)
                with session.get(url) as res:
                    data = res.json()
                try:
                    c = data['data'][self.section_generic][self.section_media]['count']
                    self._total = int(math.ceil(c / self.PAGE_SIZE))
                except (KeyError, TypeError):
                    self._total = 0
                yield data['data']

            except KeyError as e:
                time.sleep(10)

    def __length_hint__(self):
        if self._total is None:
            try:
                data = next(self._data_it)
                c = data[self.section_generic][self.section_media]['count']
                self._total = int(math.ceil(c / self.PAGE_SIZE))
            except (StopIteration, TypeError):
                self._total = 0
        return self._total - self._done

    def __iter__(self):
        return self

    def __next__(self):

        if self._finished:
            raise StopIteration

        data = next(self._data_it)

        try:
            media_info = data[self.section_generic][self.section_media]
        except (TypeError, KeyError):
            self._finished = True
            raise StopIteration

        if not media_info['page_info']['has_next_page']:
            self._finished = True
        elif not media_info['edges']:
            self._finished = True
            raise StopIteration
        else:
            self._cursor = media_info['page_info']['end_cursor']
            self._current_page += 1

        return data[self.section_generic]

    if six.PY2:
        next = __next__


class HashtagIterator(PageIterator):
    """An iterator over the pages refering to a specific hashtag.
    """

    QUERY_ID = "17882293912014529"
    URL = "{}?query_id={}&variables={{}}".format(PageIterator.BASE_URL, QUERY_ID)

    section_generic = "hashtag"
    section_media = "edge_hashtag_to_media"

    def __init__(self, hashtag, session, rhx):
        super(HashtagIterator, self).__init__(session, rhx)
        self.hashtag = hashtag

    def _getparams(self, cursor):
        return {
            "tag_name": self.hashtag,
            "first": self.PAGE_SIZE,
            "after": cursor
        }


class ProfileIterator(PageIterator):
    """An iterator over the pages of a user profile.
    """

    QUERY_HASH = "472f257a40c653c64c666ce877d59d2b"
    URL = "{}?query_hash={}&variables={{}}".format(PageIterator.BASE_URL, QUERY_HASH)

    section_generic = "user"
    section_media = "edge_owner_to_timeline_media"

    @classmethod
    def _user_data(cls, username, session):
        url = "https://www.instagram.com/{}/".format(username)
        try:
            with session.get(url) as res:
                return get_shared_data(res.text)
        except (ValueError, AttributeError):
            raise ValueError("account not found: {}".format(username))

    @classmethod
    def from_username(cls, username, session):
        user_data = cls._user_data(username, session)
        data = user_data['entry_data']['ProfilePage'][0]['graphql']['user']
        if data['is_private'] and not data['followed_by_viewer']:
            connected_id = next((ck.value for ck in session.cookies
                                 if ck.name=="ds_user_id"), None)
            if connected_id != data['id']:
                raise RuntimeError("user '{}' is private".format(username))
        return cls(data['id'], session, user_data['rhx_gis'])

    def __init__(self, owner_id, session, rhx):
        super(ProfileIterator, self).__init__(session, rhx)
        self.owner_id = owner_id

    def _getparams(self, cursor):
        return {
            "id": self.owner_id,
            "first": self.PAGE_SIZE,
            "after": cursor,
        }
