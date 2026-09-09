import tempfile, unittest
from pathlib import Path
from prediction_ledger import Prediction, connect, save, settle_due, summary

class LedgerTest(unittest.TestCase):
    def test_freeze_settle_and_score(self):
        with tempfile.TemporaryDirectory() as folder:
            db=connect(Path(folder)/'ledger.db')
            p=Prediction('p1','2026-09-10T04:00:00+08:00','2026-09-10T10:00:00+08:00','2026-09-10T03:59:59+08:00',4400,'trade','up',.6,.25,.15,4410,4420,['confirm'],['stale'],{},[])
            save(db,p)
            self.assertEqual(settle_due(db,'2026-09-10T10:00:01+08:00',4415,4422,4398),1)
            result=summary(db)
            self.assertEqual(result['samples'],1)
            self.assertEqual(result['direction_hit_rate'],1)
            self.assertEqual(result['target_range_hit_rate'],1)
            self.assertEqual(result['target_touched_rate'],1)
            self.assertFalse(result['calibration_ready'])
            db.close()

    def test_probabilities_must_sum_to_one(self):
        with tempfile.TemporaryDirectory() as folder:
            db=connect(Path(folder)/'ledger.db')
            p=Prediction('bad','2026-09-10T04:00:00+08:00','2026-09-10T10:00:00+08:00','2026-09-10T03:59:59+08:00',4400,'flat','range',.6,.3,.2,None,None,[],[],{},[])
            with self.assertRaises(ValueError): save(db,p)
            db.close()

if __name__=='__main__': unittest.main()
