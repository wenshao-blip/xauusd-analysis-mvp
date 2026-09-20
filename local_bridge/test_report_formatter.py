import json
import unittest

from report_formatter import build_report


def item(direction="up", decision="trade", support=4398, resistance=4420):
    return {
        "id": "test-report",
        "created_at": "2026-09-19T00:00:00+00:00",
        "valid_until": "2026-09-19T04:00:00+00:00",
        "price": 4410,
        "direction": direction,
        "decision": decision,
        "p_up": 0.58 if direction == "up" else 0.20,
        "p_range": 0.22,
        "p_down": 0.20 if direction == "up" else 0.58,
        "target_low": 4415,
        "target_high": 4430,
        "indicators_json": json.dumps({
            "M15": {"atr": 10, "ma20": 4405, "ma60": 4390, "ma200": 4350},
            "M30": {"ma20": 4400, "ma60": 4380, "ma200": 4320},
            "H1": {"ma20": 4398, "ma60": 4360, "ma200": 4300},
            "_structure": {
                "supports": [{"price": support}, {"price": support - 15}],
                "resistances": [{"price": resistance}, {"price": resistance + 20}],
            },
            "_market": {},
            "_candles": {},
        }),
    }


class ReportFormatterTests(unittest.TestCase):
    def test_directional_report_has_one_main_direction_and_rr(self):
        _, body = build_report(item())
        self.assertIn("【唯一主方向】\n回踩做多", body)
        self.assertIn("TP1最低风险收益门槛：1.00R", body)
        self.assertNotIn("下方方案｜突破做空", body)

    def test_flat_report_does_not_publish_two_opposing_plans(self):
        _, body = build_report(item(direction="range", decision="flat"))
        self.assertIn("【唯一主方向】\n空仓等待", body)
        self.assertNotIn("上方方案｜突破做多", body)
        self.assertNotIn("下方方案｜突破做空", body)

    def test_poor_first_target_rr_forces_flat(self):
        # A distant structural stop and nearby resistance fail the 1R gate.
        _, body = build_report(item(support=4408, resistance=4412))
        self.assertIn("【唯一主方向】\n空仓等待", body)
        self.assertIn("不足以提供至少 1:1", body)


if __name__ == "__main__":
    unittest.main()
