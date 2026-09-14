import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import patch
import broker_clock


class ClockTests(unittest.TestCase):
    def test_explicit_server_scope_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'clock.json'
            api = SimpleNamespace(account_info=lambda: SimpleNamespace(server='test'))
            with patch.object(broker_clock, 'CONFIG', path):
                self.assertEqual(broker_clock.offset(api), 0)
                path.write_text(json.dumps(dict(server='test', offset_seconds=10800)))
                self.assertEqual(broker_clock.offset(api), 10800)
                path.write_text(json.dumps(dict(server='different', offset_seconds=10800)))
                with self.assertRaises(RuntimeError): broker_clock.offset(api)
                path.write_text(json.dumps(dict(server='test', offset_seconds=1)))
                with self.assertRaises(ValueError): broker_clock.offset(api)

    def test_query_and_returned_candle_are_inverse(self):
        start = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)
        query_start, query_end = broker_clock.interval(start, end, 10800)
        self.assertEqual(query_start.hour, 3)
        self.assertEqual(query_end.hour, 5)
        class Rates(list):
            dtype = SimpleNamespace(names=['time', 'close'])
        rates = Rates([(int(query_start.timestamp()), 4300)])
        self.assertEqual(broker_clock.candles(rates,10800), [{'time':int(start.timestamp()),'close':4300}])
        self.assertEqual(rates[0][0], int(query_start.timestamp()))
