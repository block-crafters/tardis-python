import asyncio
import gzip
import logging
import json
import os
import tempfile

from time import time
from typing import List
from collections import namedtuple
from datetime import datetime, timedelta

from tardis_client.consts import EXCHANGES, EXCHANGE_CHANNELS_INFO
from tardis_client.handy import get_slice_cache_path
from tardis_client.channel import Channel

Response = namedtuple("Response", ["local_timestamp", "message"])

DATE_MESSAGE_SPLIT_INDEX = 28
DEFAULT_CACHE_DIR = os.path.join(tempfile.gettempdir(), ".tardis-cache")


class TardisClient:
    def __init__(self, endpoint="https://tardis.dev/api", cache_dir=DEFAULT_CACHE_DIR, api_key=""):
        self.logger = logging.getLogger(__name__)
        self.endpoint = endpoint
        self.cache_dir = cache_dir
        self.api_key = api_key

        self.logger.debug("initialized with: %s", {"endpoint": endpoint, "cache_dir": cache_dir, "api_key": api_key})

    async def replay(
        self, exchange: str, from_date: str, to_date: str, filters: List[Channel] = [], decode_response=True
    ):

        self._validate_payload(exchange, from_date, to_date, filters)
        from_date = datetime.fromisoformat(from_date)
        to_date = datetime.fromisoformat(to_date)
        current_slice_date = from_date
        start_time = time()

        self.logger.debug(
            "replay for '%s' exchange started from: %s, to: %s, filters: %s",
            exchange,
            from_date.isoformat(),
            to_date.isoformat(),
            filters,
        )

        while current_slice_date < to_date:
            current_slice_path = None
            while current_slice_path is None:
                path_to_check = get_slice_cache_path(self.cache_dir, exchange, current_slice_date, filters)

                self.logger.debug("getting slice: %s", path_to_check)

                if os.path.isfile(path_to_check):
                    current_slice_path = path_to_check
                else:
                    # todo check process erorors
                    self.logger.debug("waiting for slice: %s", path_to_check)
                    await asyncio.sleep(0.3)
            messages_count = 0
            with gzip.open(current_slice_path, "rb") as file:
                for line in file:
                    if len(line) == 0:
                        continue
                    messages_count = messages_count + 1
                    if decode_response:
                        # TODO comment about parsing date
                        timestamp = datetime.strptime(
                            line[0 : DATE_MESSAGE_SPLIT_INDEX - 2].decode("utf-8"), "%Y-%m-%dT%H:%M:%S.%f"
                        )
                        yield Response(timestamp, json.loads(line[DATE_MESSAGE_SPLIT_INDEX + 1 :]))
                    else:
                        yield Response(line[0:DATE_MESSAGE_SPLIT_INDEX], line[DATE_MESSAGE_SPLIT_INDEX + 1 :])

            self.logger.debug("processed slice: %s, messages count: %i", current_slice_path, messages_count)
            current_slice_date = current_slice_date + timedelta(seconds=60)

        end_time = time()

        self.logger.debug(
            "replay for '%s' exchange finished from: %s, to: %s, filters: %s, total time: %s seconds",
            exchange,
            from_date.isoformat(),
            to_date.isoformat(),
            filters,
            end_time - start_time,
        )

    def _validate_payload(self, exchange, from_date, to_date, filters):
        if exchange not in EXCHANGES:
            raise ValueError(
                f"Invalid 'exchange' argument: {exchange}. Please provide one of the following exchanges: {sEXCHANGES.join(', ')}."
            )

        if from_date is None or self._try_parse_as_iso_date(from_date) is False:
            raise ValueError(
                f"Invalid 'from_date' argument: {from_date}. Please provide valid ISO date string. https://docs.python.org/3/library/datetime.html#datetime.date.fromisoformat"
            )

        if to_date is None or self._try_parse_as_iso_date(to_date) is False:
            raise ValueError(
                f"Invalid 'to_date' argument: {to_date}. Please provide valid ISO date string. https://docs.python.org/3/library/datetime.html#datetime.date.fromisoformat"
            )

        if datetime.fromisoformat(from_date) >= datetime.fromisoformat(to_date):
            raise ValueError(
                "Invalid 'from_date' and 'to_date' arguments combination. Please provide 'to_date' date string that is later than 'from_date'."
            )

        if filters is None:
            return

        if isinstance(filters, list) is False:
            raise ValueError("Invalid 'filters' argument. Please provide valid filters Channel list")

        if len(filters) > 0:
            for filter in filters:
                if filter.name not in EXCHANGE_CHANNELS_INFO[exchange]:
                    valid_channels = ", ".join(EXCHANGE_CHANNELS_INFO[exchange])
                    raise ValueError(
                        f"Invalid 'name' argument: {filter.name}. Please provide one of the following channels: {valid_channels}."
                    )

                if filter.symbols is None:
                    continue

                if isinstance(filter.symbols, list) is False or any(
                    isinstance(symbol, str) == False for symbol in filter.symbols
                ):
                    raise ValueError(
                        f"Invalid 'symbols[]' argument: {filter.symbols}. Please provide list of symbol strings."
                    )

    def _try_parse_as_iso_date(self, date_string):
        try:
            datetime.fromisoformat(date_string)
            return True
        except ValueError:
            return False

