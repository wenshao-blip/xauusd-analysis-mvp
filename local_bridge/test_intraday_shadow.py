import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import intraday_shadow as shadow
from prediction_ledger import connect, summary


def market(now):
    bars = [{'time': int((now-timedelta(days=65-i)).timestamp()), 'open': 100,
             'close': 100+i*.1, 'high': 110, 'low': 90} for i in range(65)]
    bars[-1].update(high=108, low=104)
    m15 = [{'time': int((now-timedelta(minutes=15*(22-i))).timestamp()),
            'open': 105, 'high': 107, 'low': 103, 'close': 105} for i in range(22)]
    return {'bid': 106, 'ask': 106.2, 'time_msc': now.timestamp()*1000,
            'candles': {'D1': bars, 'M15': m15}}


def baseline(now):
    return {'valid_until': shadow.stamp(now+timedelta(hours=2)), 'direction': 'up',
            'decision': 'trade', 'p_up': .6, 'p_range': .25, 'p_down': .15,
            'execution': [], 'abandon': [], 'model_version': 'technical-structure-v3'}


class ShadowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name)/'test.db')
        shadow.initialize(self.db)
        self.now = datetime(2026, 9, 14, 8, 30, tzinfo=shadow.BJ)
        self.news = {'complete': True, 'events': [], 'errors': []}

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_at(self, now, **kwargs):
        return shadow.run(self.db, market(now), self.news, baseline(now), now,
                          lambda *_: [], **kwargs)

    def test_draft_excluded_and_daily_freezes(self):
        draft = self.run_at(self.now-timedelta(hours=2))
        self.assertIsNone(draft['daily'])
        self.assertEqual(draft['daily_stats']['samples'], 0)
        frozen = self.run_at(self.now)['daily']
        again = self.run_at(self.now+timedelta(minutes=2))['daily']
        self.assertEqual(frozen, again)
        self.assertEqual(frozen['valid_until'], '2026-09-14T22:00:00+00:00')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM shadow_forecasts WHERE kind='short'").fetchone()[0], 1)
        self.assertIsNotNone(shadow.active_daily(self.db, self.now+timedelta(hours=21, minutes=29)))
        self.assertIsNone(shadow.active_daily(self.db, self.now+timedelta(hours=21, minutes=30)))

    def test_no_late_backfill_or_manual_freeze(self):
        self.assertIsNone(self.run_at(self.now, scheduled=False)['daily'])
        self.assertIsNone(self.run_at(self.now+timedelta(minutes=10))['daily'])

    def test_utc_schedule(self):
        self.assertIsNotNone(self.run_at(self.now.astimezone(timezone.utc))['daily'])

    def test_weekend_and_stale_quotes_do_not_create_daily(self):
        self.assertIsNone(self.run_at(self.now-timedelta(days=1))['daily'])
        raw = market(self.now)
        raw['time_msc'] -= 3600*1000
        result = shadow.run(self.db, raw, self.news, baseline(self.now), self.now, lambda *_: [])
        self.assertIsNone(result['daily'])
        self.assertEqual(result['short']['decision'], 'flat')

    def test_aligned_preserves_baseline_and_conflict_reduces_confidence(self):
        base = baseline(self.now)
        original = copy.deepcopy(base)
        daily = {'id': 'd', 'direction': 'up'}
        aligned = shadow.short_forecast(market(self.now), self.news, base, daily, self.now)
        self.assertEqual(aligned['p_up'], .6)
        self.assertEqual(aligned['decision'], 'trade')
        daily['direction'] = 'down'
        conflict = shadow.short_forecast(market(self.now), self.news, base, daily, self.now)
        self.assertLess(conflict['p_up'], .6)
        self.assertAlmostEqual(sum(conflict[k] for k in ('p_up', 'p_range', 'p_down')), 1)
        self.assertEqual(conflict['decision'], 'flat')
        self.assertEqual(base, original)

    def test_only_closed_m15_breakout_confirms(self):
        raw = market(self.now)
        raw['candles']['M15'].append({'time': self.now.timestamp(), 'high': 130, 'low': 100, 'close': 129})
        self.assertFalse(shadow.m15_confirmed(raw, 'up', self.now))
        raw['candles']['M15'][-2]['close'] = 108
        raw['candles']['M15'][-2]['high'] = 109
        result = shadow.short_forecast(raw, self.news, baseline(self.now), {'id':'d','direction':'down'}, self.now)
        self.assertTrue(result['m15_confirmed'])
        self.assertEqual(result['decision'], 'trade')

    def test_atr_boundary_and_current_day_not_in_atr(self):
        raw = market(self.now)
        raw['candles']['D1'][-1].update(high=116, low=100)
        vol = shadow.volatility(raw)
        self.assertEqual(vol['atr'], 20)
        self.assertEqual(vol['remaining'], 4)
        self.assertTrue(vol['no_chase'])
        result = shadow.short_forecast(raw, self.news, baseline(self.now), {'id':'d','direction':'up'}, self.now)
        self.assertEqual(result['decision'], 'flat')
        raw['candles']['D1'][-1]['high'] = 115.99
        self.assertFalse(shadow.volatility(raw)['no_chase'])
        raw['candles']['D1'][-1]['high'] = 130
        self.assertEqual(shadow.volatility(raw)['remaining'], 0)

    def test_missing_news_blocks_shadow(self):
        result = shadow.short_forecast(market(self.now), {}, baseline(self.now), {'id':'d','direction':'up'}, self.now)
        self.assertEqual(result['decision'], 'flat')
        self.assertEqual(result['news_risk']['level'], 'unverified')

    def test_separate_settlement_and_no_future_close(self):
        self.run_at(self.now)
        ranges = []
        def history(start, end):
            ranges.append((start, end))
            return [{'time': t, 'high': 109, 'low': 105, 'close': 108}
                    for t in range(int(start.timestamp()), int(end.timestamp()), 300)] + [
                        {'time': int(end.timestamp()), 'high': 1000, 'low': 1, 'close': 1}]
        shadow.settle(self.db, self.now+timedelta(hours=23), history)
        result = shadow.export(self.db, self.now+timedelta(hours=23))
        self.assertEqual(result['daily_stats']['samples'], 1)
        self.assertEqual(result['short_stats']['samples'], 1)
        self.assertEqual(result['settled_trading_days'], 1)
        self.assertEqual(summary(self.db)['samples'], 0)
        self.assertEqual({(b-a).total_seconds()/3600 for a,b in ranges}, {2,21.5})
        for row in self.db.execute('SELECT settlement FROM shadow_forecasts'):
            self.assertEqual(json.loads(row[0])['actual_close'], 108)

    def test_missing_history_stays_pending(self):
        self.run_at(self.now)
        shadow.settle(self.db, self.now+timedelta(days=2), lambda *_: [])
        result = shadow.export(self.db, self.now+timedelta(days=2))
        self.assertEqual(result['daily_stats']['samples'], 0)
        self.assertEqual(result['pending'], 2)

    def test_30_days_review_only_and_drafts_never_count(self):
        for i in range(30):
            item = shadow.daily_forecast(market(self.now), self.news, self.now, 'daily')
            item['id'] = str(i)
            shadow.put(self.db, item, 'daily', str(i))
        self.db.execute('UPDATE shadow_forecasts SET settlement=?', (json.dumps({'direction_hit':1,'brier':0}),))
        self.db.commit()
        result = shadow.export(self.db, self.now)
        self.assertTrue(result['review_ready'])
        self.assertFalse(result['auto_promote'])
        self.assertEqual(result['settled_trading_days'], 30)

    def test_report_labels_and_independent_stats(self):
        result = self.run_at(self.now)
        text = shadow.report(result)
        self.assertIn('冻结定调', text)
        self.assertIn('未经校准', text)
        self.assertIn('固定会话影子', text)


if __name__ == '__main__':
    unittest.main()
