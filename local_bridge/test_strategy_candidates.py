import unittest

from strategy_candidates import select_strategy


def market(signals, trend="up", adx=28, price=4410):
    up = trend == "up"
    def tf(close, ma20, ma60, weight=1):
        return {"close": close, "ma20": ma20, "ma60": ma60, "ma200": ma60 - 20,
                "macd_hist": weight if up else -weight, "adx": adx,
                "+di": 30 if up else 12, "-di": 12 if up else 30, "atr": 10}
    candles=[]
    for i in range(24):
        close=4400+i*.2
        candles.append({"open":close-.1,"high":close+.5,"low":close-.5,"close":close})
    return {
        "bid": price - .1, "ask": price + .1, "spread": .2,
        "candles": {"M5": candles},
        "indicators": {
            "H1": tf(price, price - 5 if up else price + 5, price - 15 if up else price + 15),
            "M30": tf(price, price - 3 if up else price + 3, price - 10 if up else price + 10),
            "M15": tf(price, price - 2 if up else price + 2, price - 7 if up else price + 7),
            "M5": tf(price, price - 1 if up else price + 1, price - 4 if up else price + 4),
            "_candles": {"M5": [{"type": value, "bias": "up" if "up" in value or "bullish" in value else "down", "label": value} for value in signals]},
            "_structure": {
                "supports": [{"price": 4398}, {"price": 4405}],
                "resistances": [{"price": 4415}, {"price": 4430}],
            },
        },
    }


class StrategyCandidateTests(unittest.TestCase):
    def test_confirmed_breakout_can_be_selected(self):
        result = select_strategy(market(["breakout_up"]), {"complete": True}, "up")
        self.assertEqual(result["name"], "breakout_long")
        self.assertGreaterEqual(result["score"], 65)
        self.assertGreaterEqual(result["rr_tp1"], 1)
        self.assertEqual(result["score_breakdown"][0]["points"],50)
        self.assertIn("selection_reason",result)
        self.assertEqual(len(result["candidates"]),8)
        self.assertTrue(any(x["status"]=="not_triggered" for x in result["candidates"]))

    def test_pullback_can_be_selected_in_trend(self):
        result = select_strategy(market(["bullish_engulfing"], price=4407), {"complete": True}, "up")
        self.assertEqual(result["name"], "pullback_long")

    def test_missing_news_forces_flat_but_keeps_candidate_audit(self):
        result = select_strategy(market(["breakout_up"]), {"complete": False}, "up")
        self.assertEqual(result["name"], "flat")
        self.assertTrue(result["candidates"])
        self.assertIn("新闻数据不完整", result["reasons"])

    def test_no_confirmation_forces_flat(self):
        result = select_strategy(market([]), {"complete": True}, "up")
        self.assertEqual(result["name"], "flat")
        self.assertIn("NO_QUALIFIED_CANDIDATE",result["hard_rejections"])

    def test_false_breakout_short_is_a_distinct_candidate(self):
        sample=market(["upper_rejection"], trend="down", price=4408)
        bars=sample["candles"]["M5"]
        for i in range(len(bars)-2):
            bars[i]={"open":4410,"high":4414,"low":4408,"close":4411}
        bars[-3]["high"]=4415
        prior_high=max(x["high"] for x in bars[:-2])
        bars[-2]={"open":prior_high-.3,"high":prior_high+2,"low":prior_high-1,"close":prior_high-.2}
        bars[-1]={"open":prior_high-.1,"high":prior_high,"low":prior_high-2,"close":prior_high-1.2}
        result=select_strategy(sample,{"complete":True},"down")
        self.assertEqual(result["name"],"false_breakout_short")


if __name__ == "__main__":
    unittest.main()
