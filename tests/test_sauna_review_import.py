from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.sauna_review_import import build_summary, import_review, parse_review_text


TEMPLATE_REVIEW = """施設名：和

🔥 一言まとめ（キャッチコピー）：3分で仕上がる

総合評価（10点満点）：9

- 好きだった点
  #サウナ：100度で湿度も十分
  #水風呂：5度
  #外気浴：普通
  #導線：水風呂が近い
  #混み具合：空いている

- 微妙だった点：

- 混雑（時間帯）：朝

- メモ（次回の入り方・持ち物・リピ条件）：短時間で行く
"""

FORMATTED_REVIEW = """## 🧖‍♂️ 星野温泉

**さすが星野リゾート。これは秘境サウナ。**
**総合評価：★★★★☆（7/10）**

### #サウナ
温度は92℃。湿度が高く、体感は100℃弱。

### #水風呂
岩で仕切られ、チラーも入っている。

### #外気浴
椅子は少ないが混まない。

### #導線
水風呂の目の前が椅子で、サウナも近い。

### #混み具合
比較的空いている。

### 総評
秘境感と機能性が同居している。
"""


class ParseReviewTests(unittest.TestCase):
    def test_parses_input_template(self) -> None:
        review = parse_review_text(TEMPLATE_REVIEW)
        self.assertEqual(review["facility"], "和")
        self.assertEqual(review["score"], 9)
        self.assertIn("100度", review["sauna"])
        self.assertEqual(review["crowd_time"], "朝")

    def test_parses_polished_markdown_review(self) -> None:
        review = parse_review_text(FORMATTED_REVIEW)
        self.assertEqual(review["facility"], "星野温泉")
        self.assertEqual(review["score"], 7)
        self.assertEqual(review["catchcopy"], "さすが星野リゾート。これは秘境サウナ。")
        self.assertIn("チラー", review["cold_bath"])
        self.assertNotIn("秘境感と機能性", review["crowd"])

    def test_duplicate_import_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "review.txt"
            data_path = root / "reviews.json"
            summary_path = root / "summary.json"
            input_path.write_text(TEMPLATE_REVIEW, encoding="utf-8")

            first, first_created = import_review(
                input_path, data_path, summary_path, "2026-07-26", "test"
            )
            second, second_created = import_review(
                input_path, data_path, summary_path, "2026-07-26", "test"
            )

            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first["id"], second["id"])
            dataset = json.loads(data_path.read_text(encoding="utf-8"))
            self.assertEqual(len(dataset["reviews"]), 1)

    def test_summary_groups_repeat_visits(self) -> None:
        summary = build_summary([
            {"facility": "和", "score": 9, "tags": ["高温"]},
            {"facility": "和", "score": 8, "tags": ["グルシン"]},
            {"facility": "北欧", "score": 10, "tags": []},
        ])
        self.assertEqual(summary["review_count"], 3)
        self.assertEqual(summary["facility_count"], 2)
        self.assertEqual(summary["rankings"][0]["facility"], "北欧")
        wa = next(item for item in summary["rankings"] if item["facility"] == "和")
        self.assertEqual(wa["visits"], 2)
        self.assertEqual(wa["average_score"], 8.5)


if __name__ == "__main__":
    unittest.main()
