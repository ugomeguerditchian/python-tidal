# -*- coding: utf-8 -*-
#
# Copyright (C) 2019-2022 morguldir
# Copyright (C) 2014 Thomas Amland
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""A module containing functions relating to TIDAL api requests."""

import json
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Literal,
    Mapping,
    Optional,
    Union,
    cast,
)
from urllib.parse import urljoin

from tidalapi.types import JsonObj

log = logging.getLogger(__name__)

Params = Mapping[str, Union[str, int, None]]

if TYPE_CHECKING:
    from tidalapi.session import Session


class Requests(object):
    """A class for handling api requests to TIDAL."""

    def __init__(self, session):
        self.session = session
        self.config = session.config

    def basic_request(self, method, path, params=None, data=None, headers=None):
        request_params = {
            "sessionId": self.session.session_id,
            "countryCode": self.session.country_code,
            "limit": self.config.item_limit,
        }

        if params:
            # Don't update items with a none value, as we prefer a default value.
            # requests also does not support them.
            not_none = filter(lambda item: item[1] is not None, params.items())
            request_params.update(not_none)

        if not headers:
            headers = {}
        if self.session.token_type:
            headers["authorization"] = (
                self.session.token_type + " " + self.session.access_token
            )

        url = urljoin(self.session.config.api_location, path)
        request = self.session.request_session.request(
            method, url, params=request_params, data=data, headers=headers
        )

        refresh_token = self.session.refresh_token
        if not request.ok and refresh_token:
            json_resp = None
            try:
                json_resp = request.json()
            except json.decoder.JSONDecodeError:
                pass

            if json_resp and json_resp.get("userMessage", "").startswith(
                "The token has expired."
            ):
                log.debug("The access token has expired, trying to refresh it.")
                refreshed = self.session.token_refresh(refresh_token)
                if refreshed:
                    request = self.basic_request(method, url, params, data, headers)
            else:
                log.warning("HTTP error on %d", request.status_code)
                log.debug("Response text\n%s", request.text)

        return request

    def request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        params: Optional[Params] = None,
        data: Optional[JsonObj] = None,
        headers: Optional[Mapping[str, str]] = None,
    ):
        """Method for tidal requests.

        Not meant for use outside of this library.

        :param method: The type of request to make
        :param path: The TIDAL api endpoint you want to use.
        :param params: The parameters you want to supply with the request.
        :param data: The data you want to supply with the request.
        :param headers: The headers you want to include with the request
        :return: The json data at specified api endpoint.
        """

        request = self.basic_request(method, path, params, data, headers)
        log.debug("request: %s", request.request.url)
        request.raise_for_status()
        if request.content:
            log.debug("response: %s", json.dumps(request.json(), indent=4))
        return request

    def map_request(
        self,
        url: str,
        params: Optional[Params] = None,
        parse: Optional[Callable] = None,
    ):
        """Returns the data about object(s) at the specified url, with the method
        specified in the parse argument.

        Not meant for use outside of this library

        :param url: TIDAL api endpoint that contains the data
        :param params: TIDAL parameters to use when getting the data
        :param parse: The method used to parse the data at the url
        :return: The object(s) at the url, with the same type as the class of the parse
            method.
        """
        json_obj = self.request("GET", url, params).json()

        return self.map_json(json_obj, parse=parse)

    @classmethod
    def map_json(
        cls,
        json_obj: JsonObj,
        parse: Optional[Callable] = None,
        session: Optional["Session"] = None,
    ) -> List[Any]:
        items = json_obj.get("items")

        if items is None:
            if parse is None:
                raise ValueError("A parser must be supplied")
            return parse(json_obj)

        if len(items) > 0 and "item" in items[0]:
            # Move created date into the item json data like it is done for playlists tracks.
            if "created" in items[0]:
                for item in items:
                    item["item"]["dateAdded"] = item["created"]

            lists: List[Any] = []
            for item in items:
                if session is not None:
                    parse = cast(
                        Callable,
                        session.convert_type(
                            cast(str, item["type"]).lower() + "s", output="parse"
                        ),
                    )
                if parse is None:
                    raise ValueError("A parser must be supplied")
                lists.append(parse(item["item"]))

            return lists
        if parse is None:
            raise ValueError("A parser must be supplied")
        return list(map(parse, items))

    def get_items(self, url, parse):
        """Returns a list of items, used when there are over a 100 items, but TIDAL
        doesn't always allow more specifying a higher limit.

        Not meant for use outside of this library.

        :param url: TIDAL api endpoint where you get the objects.
        :param parse: The method that parses the data in the url
        item_List: List[Any] = []
        """

        params = {"offset": 0, "limit": 100}
        remaining = 100
        item_list: List[Any] = []
        while remaining == 100:
            items = self.map_request(url, params=params, parse=parse)
            remaining = len(items)
            params["offset"] += 100
            item_list.extend(items or [])
        return item_list
