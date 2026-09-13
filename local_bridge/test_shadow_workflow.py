"""End-to-end export with simulated market inputs and no external side effects."""
import contextlib
import io
import json
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Notification credentials and OS keyring are intentionally outside this test.
notifications = types.ModuleType('notifications')
notifications.send_all = lambda *_: None
with patch.dict('sys.modules', {'notifications': notifications}):
    import workflow


class WorkflowTest(unittest.TestCase):
    def test_v3_export_and_shadow_are_separate(self):
        now = datetime.now(timezone.utc)
        candles = {}
        for tf, seconds in [('D1',86400), ('H1',3600), ('M30',1800), ('M15',900), ('M5',300)]:
            candles[tf] = [dict(time=int(now.timestamp())-(240-i)*seconds,
                                open=100+i*.01, close=100.1+i*.01,
                                high=101+i*.01, low=99+i*.01) for i in range(240)]
        raw = dict(candles=candles, bid=102.5, ask=102.6, time_msc=now.timestamp()*1000)
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            dbpath, web = Path(temp)/'ledger.db', Path(temp)/'dashboard.json'
            stack.enter_context(patch.object(workflow, 'DB', dbpath))
            stack.enter_context(patch.object(workflow, 'WEB', web))
            stack.enter_context(patch.object(workflow, 'mt5_snapshot', return_value=raw))
            stack.enter_context(patch.object(workflow, 'news_collect', return_value={'complete':True,'articles':[],'events':[],'errors':[]}))
            send = stack.enter_context(patch.object(workflow, 'send_all'))
            publish = stack.enter_context(patch.object(workflow, 'publish_dashboard'))
            stack.enter_context(patch('sys.argv', ['workflow.py','--no-push','--no-publish']))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            workflow.main()
            data = json.loads(web.read_text('utf-8'))
            self.assertIsNone(data['shadow_error'])
            self.assertEqual(data['current']['model_version'], 'technical-structure-v3')
            self.assertEqual(data['rolling20']['samples'], 0)
            self.assertIn('日内影子版本', data['shadow']['report_text'])
            self.assertEqual(data['shadow']['model_version'], 'intraday-shadow-v1')
            send.assert_not_called()
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
