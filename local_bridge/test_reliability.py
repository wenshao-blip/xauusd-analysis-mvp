import contextlib
import io
import json
import subprocess
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import intraday_shadow as shadow
import operations
import settlement_audit as audit
from prediction_ledger import Prediction, connect, save, settle_history, summary
from workflow_lock import acquire
from control_server import scheduled_due

notifications=types.ModuleType('notifications')
notifications.send_all=lambda *_:{}
with patch.dict('sys.modules',{'notifications':notifications}):
    import workflow


NOW=datetime(2026,9,14,8,tzinfo=shadow.BJ)


def path(start,end,close=108):
    first=int(start.timestamp()+299)//300*300
    return [dict(time=t,high=max(110,close),low=min(100,close),close=close)
            for t in range(first,int(end.timestamp())//300*300,300)]


def prediction(pid,start,end):
    return Prediction(pid,start.isoformat(),end.isoformat(),start.isoformat(),106,'trade','up',
                      .6,.25,.15,107,110,[],[],{},[],model_version='technical-structure-v3',run_type='scheduled_2h')


def market(now):
    candles={}
    for tf,seconds in [('D1',86400),('H1',3600),('M30',1800),('M15',900),('M5',300)]:
        candles[tf]=[dict(time=int(now.timestamp())-(240-i)*seconds,
                         open=100+i*.01,close=100.1+i*.01,high=101+i*.01,low=99+i*.01) for i in range(240)]
    return dict(candles=candles,bid=102.5,ask=102.6,time_msc=now.timestamp()*1000)


class Clock(datetime):
    @classmethod
    def now(cls,tz=None):
        return NOW.astimezone(tz or timezone.utc)


class ReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.file=Path(self.temp.name)/'ledger.db'
        self.db=connect(self.file)
        operations.initialize(self.db,NOW-timedelta(days=1))
        shadow.initialize(self.db)

    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def test_history_validation_rejects_internal_gap_and_missing_end(self):
        start,end=NOW,NOW+timedelta(hours=2)
        bars=path(start,end)
        self.assertEqual(audit.path_for(lambda *_:bars[:10]+bars[11:],start,end)[1],'history_gap')
        self.assertEqual(audit.path_for(lambda *_:bars[:-1],start,end)[1],'missing_end')
        self.assertEqual(audit.path_for(lambda *_:bars[1:],start,end)[1],'missing_start')

    def test_bad_numbers_and_conflicting_duplicates(self):
        start,end=NOW,NOW+timedelta(hours=2)
        bars=path(start,end)
        self.assertEqual(audit.path_for(lambda *_:bars+[dict(bars[0],close=109)],start,end)[1],'invalid_bar')
        bars[2]['close']=float('nan')
        self.assertEqual(audit.path_for(lambda *_:bars,start,end)[1],'invalid_bar')

    def test_non_grid_window_never_uses_future_bar(self):
        start=NOW+timedelta(seconds=17);end=start+timedelta(hours=2)
        bars=path(start,end)+[dict(time=int(end.timestamp())//300*300,high=1000,low=1,close=1)]
        result,reason,_=audit.path_for(lambda *_:bars,start,end)
        self.assertEqual(reason,'settled');self.assertEqual(result['close'],108)

    def test_old_predictions_use_different_paths_and_keep_settled_immutable(self):
        save(self.db,prediction('a',NOW-timedelta(hours=4),NOW-timedelta(hours=2)))
        save(self.db,prediction('b',NOW-timedelta(hours=2),NOW))
        def history(start,end):
            return path(start,end,108 if end<NOW else 104)
        self.assertEqual(settle_history(self.db,NOW,history),2)
        rows=self.db.execute('SELECT actual_close FROM predictions ORDER BY id').fetchall()
        self.assertEqual([r[0] for r in rows],[108,104])
        self.assertEqual(summary(self.db)['samples'],2)
        self.assertEqual(settle_history(self.db,NOW+timedelta(days=1),lambda *_:[]),0)

    def test_missing_history_retry_survives_reconnect(self):
        save(self.db,prediction('a',NOW-timedelta(hours=2),NOW))
        settle_history(self.db,NOW,lambda *_:[])
        self.assertEqual(audit.summary(self.db,NOW)['pending'],1)
        self.db.close();self.db=connect(self.file)
        settle_history(self.db,NOW,path)
        self.assertEqual(audit.summary(self.db,NOW)['pending'],0)
        self.assertEqual(self.db.execute('SELECT attempts FROM settlement_audit').fetchone()[0],2)

    def test_one_history_failure_does_not_block_other_prediction(self):
        save(self.db,prediction('a',NOW-timedelta(hours=4),NOW-timedelta(hours=2)))
        save(self.db,prediction('b',NOW-timedelta(hours=2),NOW))
        def history(start,end):
            if end<NOW: raise RuntimeError('secret-token-must-not-leak')
            return path(start,end)
        settle_history(self.db,NOW,history)
        status=audit.summary(self.db,NOW)
        self.assertEqual(status['pending'],1)
        self.assertEqual(status['items'][0]['reason'],'history_error')
        self.assertNotIn('secret-token',json.dumps(status))

    def test_unchecked_due_rows_visible_and_drafts_excluded(self):
        save(self.db,prediction('a',NOW-timedelta(hours=2),NOW))
        item={'id':'draft','created_at':shadow.stamp(NOW-timedelta(hours=2)),'valid_until':shadow.stamp(NOW)}
        shadow.put(self.db,item,'draft','2026-09-14')
        result=audit.summary(self.db,NOW)
        self.assertEqual(result['pending'],1)
        self.assertEqual(result['items'][0]['reason'],'pending_check')

    def test_budget_defers_without_fabricating_data_error(self):
        save(self.db,prediction('a',NOW-timedelta(hours=2),NOW))
        def history(*_): raise audit.BudgetDeferred()
        self.assertEqual(settle_history(self.db,NOW,history),0)
        self.assertEqual(audit.summary(self.db,NOW)['items'][0]['reason'],'pending_check')

    def test_missing_schedule_survives_restart_and_weekend_excluded(self):
        sunday=NOW-timedelta(days=1)
        self.assertEqual(operations.health(self.db,sunday)['missed_count'],0)
        result=operations.health(self.db,NOW+timedelta(minutes=11))
        self.assertEqual(result['missed_count'],3) # draft, daily, 08:00 short
        self.db.close();self.db=connect(self.file)
        self.assertEqual(operations.health(self.db,NOW+timedelta(minutes=11))['missed_count'],3)

    def test_no_backdated_misses_before_enablement(self):
        operations.set_value(self.db,'monitor_since',operations.stamp(NOW+timedelta(minutes=30)))
        self.assertEqual(operations.health(self.db,NOW+timedelta(hours=1))['missed_count'],0)

    def test_scheduled_retry_and_generated_report_deduplication(self):
        key=operations.job_key(NOW,'scheduled_2h')
        operations.start(self.db,key,'scheduled_2h',NOW)
        operations.update(self.db,key,'finished','mt5_error',now=NOW)
        self.assertIsNone(scheduled_due(self.db,NOW+timedelta(seconds=20)))
        self.assertEqual(scheduled_due(self.db,NOW+timedelta(minutes=2)),[])
        operations.update(self.db,key,'finished','publish_error','existing',NOW)
        self.assertIsNone(scheduled_due(self.db,NOW+timedelta(minutes=2)))
        operations.update(self.db,key,'finished','shadow_error','existing',NOW)
        self.assertEqual(scheduled_due(self.db,NOW+timedelta(minutes=2)),[])
        self.assertIsNone(scheduled_due(self.db,NOW+timedelta(minutes=10)))

    def test_alert_dedup_and_failed_delivery_backoff(self):
        h={'issues':[{'key':'x','message':'test'}]}
        send=Mock(return_value={'email':{'ok':True}})
        operations.notify_changes(self.db,h,NOW,send)
        operations.notify_changes(self.db,h,NOW+timedelta(minutes=1),send)
        self.assertEqual(send.call_count,1)
        h['issues'][0]['key']='y';send.return_value={'email':{'ok':False}}
        operations.notify_changes(self.db,h,NOW+timedelta(minutes=2),send)
        operations.notify_changes(self.db,h,NOW+timedelta(minutes=3),send)
        self.assertEqual(send.call_count,2)
        operations.notify_changes(self.db,h,NOW+timedelta(hours=2),send)
        self.assertEqual(send.call_count,3)

    def test_upload_recovery_clears_alert(self):
        key=operations.job_key(NOW,'scheduled_2h')
        operations.start(self.db,key,'scheduled_2h',NOW)
        operations.update(self.db,key,'finished','publish_error','p',NOW)
        operations.set_value(self.db,'publish_pending','1')
        self.assertIn('publish_pending',[i['key'] for i in operations.health(self.db,NOW)['issues']])
        operations.set_value(self.db,'publish_pending','0')
        self.assertNotIn('run_'+key,[i['key'] for i in operations.health(self.db,NOW)['issues']])

    def test_os_lock_blocks_duplicate_and_releases(self):
        file=Path(self.temp.name)/'task.lock'
        with acquire(file) as first:
            self.assertTrue(first)
            with acquire(file) as second:self.assertFalse(second)
        with acquire(file) as third:self.assertTrue(third)

    def workflow(self,raw=None,history=None,args=None):
        stack=contextlib.ExitStack()
        stack.enter_context(patch.object(workflow,'DB',self.file))
        stack.enter_context(patch.object(workflow,'WEB',Path(self.temp.name)/'dashboard.json'))
        stack.enter_context(patch.object(workflow,'datetime',Clock))
        stack.enter_context(patch.object(workflow,'mt5_snapshot',return_value=raw or market(NOW)))
        stack.enter_context(patch.object(workflow,'mt5_history',side_effect=history or path))
        stack.enter_context(patch.object(workflow,'news_collect',return_value={'complete':True,'articles':[],'events':[]}))
        stack.enter_context(patch('sys.argv',['workflow.py','--no-push','--no-publish',*(args or [])]))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return stack

    def test_old_history_outage_cannot_block_0800_freeze(self):
        save(self.db,prediction('old',NOW-timedelta(hours=2),NOW))
        def failure(*_):raise RuntimeError('outage')
        with self.workflow(history=failure):self.assertEqual(workflow.main(),0)
        self.assertIsNotNone(shadow.active_daily(self.db,NOW))
        self.assertEqual(audit.summary(self.db,NOW)['pending'],1)

    def test_restarted_workflow_does_not_duplicate_forecast(self):
        with self.workflow():
            workflow.main();workflow.main()
        self.assertEqual(self.db.execute('SELECT count(*) FROM predictions').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM shadow_forecasts WHERE kind='daily'").fetchone()[0],1)

    def test_stale_quote_creates_health_not_formal_sample(self):
        raw=market(NOW);raw['time_msc']-=3600000
        with self.workflow(raw=raw):self.assertEqual(workflow.main(),0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM predictions').fetchone()[0],0)
        self.assertEqual(operations.get(self.db,'market_status'),'stale_quote')

    def test_shadow_failure_can_retry_without_duplicate_baseline(self):
        with self.workflow(),patch.object(shadow,'run',side_effect=ValueError('bad snapshot')):
            workflow.main()
        self.assertIsNone(shadow.active_daily(self.db,NOW))
        with self.workflow():workflow.main()
        self.assertIsNotNone(shadow.active_daily(self.db,NOW))
        self.assertEqual(self.db.execute('SELECT count(*) FROM predictions').fetchone()[0],1)

    def test_publish_retries_push_even_when_file_is_unchanged(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,'','')
        with patch.object(workflow.subprocess,'run',side_effect=run):
            self.assertTrue(workflow.publish_dashboard('test')['ok'])
        self.assertTrue(any(c[:2]==['git','push'] for c in calls))
        self.assertFalse(any(c[:2]==['git','commit'] for c in calls))


if __name__=='__main__':unittest.main()
