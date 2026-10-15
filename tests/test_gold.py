"""정답 층 합성 테스트

아래 세그먼트 · 라벨 · 주인 목록은 전부 합성 픽스처일 뿐이며 규칙과 무관하다
"""
import json
import os
import tempfile
import unittest

from labeling import gold

# 합성 픽스처일 뿐이며 규칙과 무관하다
def seg(Id, doc, source, layer, group):
  return {"segment_id": Id, "doc_id": doc, "seq": 1, "source": source, "layer": layer, "group": group, "text": "합성"}


SEGS = [
  seg("a#s1", "a", "team_1jo", "개인", "주인A"),
  seg("a#s2", "a", "team_1jo", "개인", "주인A"),
  seg("a#s3", "a", "team_1jo", "개인", "주인A"),
  seg("b#s1", "b", "team_1jo", "팀", "1조"),
  seg("b#s2", "b", "team_1jo", "팀", "1조"),
  seg("c#s1", "c", "team_soft_eng", "팀", "소공"),
  seg("c#s2", "c", "team_soft_eng", "전사", None),
  seg("d#s1", "d", "lecture_note", "전사", None),
  seg("e#s1", "e", "team_1jo", "개인", "주인A"),
]
DOC_IDS = ["a", "b", "c", "d"]


# round · criteria_sha256 값은 라벨 파일 단일성 검사용 픽스처 값일 뿐이며 규칙과 무관하다
FIXTURE_ROUND = 1
FIXTURE_CRITERIA_SHA256 = "c" * 64


def lab(Id, Intrinsic, D0=False):
  return {
    "segment_id": Id, "intrinsic_layer": Intrinsic, "default_applied": D0,
    "round": FIXTURE_ROUND, "criteria_sha256": FIXTURE_CRITERIA_SHA256,
  }


LABELS = [
  lab("a#s1", "팀"),
  lab("a#s2", "전사"),
  lab("a#s3", "전사", True),
  lab("b#s1", "개인"),
  lab("b#s2", "전사", True),
  lab("c#s1", "팀"),
  lab("c#s2", "전사", True),
]
OWNERS = ["주인A", "주인B"]


def write_jsonl(Path, Rows):
  with open(Path, "w", encoding="utf-8") as f:
    for r in Rows:
      f.write(json.dumps(r, ensure_ascii=False) + "\n")


def make(d, Segs=SEGS, Labels=LABELS, Owners=OWNERS, DocIds=DOC_IDS):
  Spl = os.path.join(d, "split")
  os.makedirs(Spl)
  with open(os.path.join(Spl, "pilot_doc_ids.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(DocIds) + "\n")
  write_jsonl(os.path.join(d, "segments.jsonl"), Segs)
  write_jsonl(os.path.join(d, "labels.jsonl"), Labels)
  with open(os.path.join(d, "source_layers.json"), "w", encoding="utf-8") as f:
    json.dump({"team_1jo_personal_owners": Owners}, f, ensure_ascii=False)
  return {
    "segments_path": os.path.join(d, "segments.jsonl"), "split_dir": Spl, "split_name": "pilot",
    "labels_path": os.path.join(d, "labels.jsonl"), "source_layers_path": os.path.join(d, "source_layers.json"),
    "out_path": os.path.join(d, "gold.jsonl"), "report_path": os.path.join(d, "report.json"),
  }


def run_ok(d, **Over):
  Kw = make(d, **Over)
  Report = gold.run(**Kw)
  with open(Kw["out_path"], encoding="utf-8") as f:
    return Report, [json.loads(l) for l in f], Kw


class TestGold(unittest.TestCase):
  def test_personal_source_team_label_goes_up_to_team_with_group(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    R = Rows[0]
    self.assertEqual((R["segment_id"], R["intrinsic_layer"], R["source_layer"], R["source_group"]), ("a#s1", "팀", "개인", "주인A"))
    self.assertEqual((R["gold_layer"], R["gold_group"], R["clamped"], R["auto"]), ("팀", "1조", False, False))
    self.assertEqual(list(R), ["segment_id", "intrinsic_layer", "source_layer", "source_group", "gold_layer", "gold_group", "clamped", "auto"])

  def test_personal_source_whole_label_has_no_group(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    self.assertEqual((Rows[1]["gold_layer"], Rows[1]["gold_group"], Rows[1]["clamped"]), ("전사", None, False))
    self.assertEqual((Rows[2]["gold_layer"], Rows[2]["gold_group"], Rows[2]["clamped"]), ("전사", None, False))

  def test_team_source_personal_label_is_clamped_to_team(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    R = Rows[3]
    self.assertEqual((R["intrinsic_layer"], R["gold_layer"], R["gold_group"], R["clamped"]), ("개인", "팀", "1조", True))
    self.assertEqual((Rows[5]["gold_layer"], Rows[5]["gold_group"]), ("팀", "소공"))

  def test_lecture_note_is_auto_with_null_intrinsic(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    R = Rows[7]
    self.assertEqual(R["segment_id"], "d#s1")
    self.assertEqual((R["intrinsic_layer"], R["gold_layer"], R["gold_group"], R["clamped"], R["auto"]), (None, "전사", None, False, True))

  def test_only_split_documents_in_segments_order(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    self.assertEqual([r["segment_id"] for r in Rows], [s["segment_id"] for s in SEGS if s["doc_id"] in DOC_IDS])

  def test_never_places_gold_below_source(self):
    # 기준 §4 : 하향 배치 정답 없음
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
    for R in Rows:
      self.assertGreaterEqual(gold.LAYER_RANK[R["gold_layer"]], gold.LAYER_RANK[R["source_layer"]], R["segment_id"])

  def test_report_counts_match_hand_count(self):
    with tempfile.TemporaryDirectory() as d:
      Report, Rows, Kw = run_ok(d)
      with open(Kw["report_path"], encoding="utf-8") as f:
        ReportFile = json.load(f)
    self.assertEqual(Report, ReportFile)
    self.assertEqual(Report["split"], "pilot")
    self.assertEqual(Report["segments"], 8)
    self.assertEqual(Report["source_layer_x_gold_layer"], {"개인>전사": 2, "개인>팀": 1, "전사>전사": 2, "팀>전사": 1, "팀>팀": 2})
    self.assertEqual(Report["clamped"], 1)
    self.assertEqual(Report["gold_gt_source"], 4)
    self.assertEqual(Report["auto"], 1)
    # D0 는 a#s3, b#s2, c#s2 셋이고, 그중 정답 > 출처는 c#s2 ( 출처 전사 ) 를 뺀 둘
    self.assertEqual(Report["d0"], 3)
    self.assertEqual(Report["d0_gold_gt_source"], 2)
    self.assertEqual(len(Report["segments_sha256"]), 64)
    self.assertEqual(len(Report["labels_sha256"]), 64)
    # 보고의 회차 · 기준판은 라벨 파일의 단일 값과 같아야 한다
    self.assertEqual(Report["label_round"], FIXTURE_ROUND)
    self.assertEqual(Report["label_criteria_sha256"], FIXTURE_CRITERIA_SHA256)

  def test_split_doc_without_segments_raises(self):
    # 분리 파일에만 있는 doc_id 는 세그먼트가 없어 조용히 빠진다
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, DocIds=DOC_IDS + ["z"])
      with self.assertRaisesRegex(ValueError, "세그먼트가 없는"):
        gold.run(**Kw)

  def test_mixed_label_round_raises(self):
    # 다른 회차 라벨이 섞이면 정답이 오염된다
    Labels = [dict(LABELS[0], round=2)] + LABELS[1:]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=Labels)
      with self.assertRaisesRegex(ValueError, "round"):
        gold.run(**Kw)

  def test_mixed_label_criteria_sha256_raises(self):
    # 다른 기준판 라벨이 섞이면 정답이 오염된다
    Labels = [dict(LABELS[0], criteria_sha256="d" * 64)] + LABELS[1:]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=Labels)
      with self.assertRaisesRegex(ValueError, "criteria_sha256"):
        gold.run(**Kw)

  def test_empty_label_file_raises(self):
    # 빈 라벨 파일은 회차 · 기준판을 확인할 수 없다
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=[])
      with self.assertRaisesRegex(ValueError, "비어 있다"):
        gold.run(**Kw)

  def test_label_missing_round_field_raises(self):
    # 회차 필드가 없는 라벨은 단일성을 확인할 수 없다
    Labels = [{k: v for k, v in LABELS[0].items() if k != "round"}] + LABELS[1:]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=Labels)
      with self.assertRaisesRegex(ValueError, "필드가 빠졌다"):
        gold.run(**Kw)

  def test_missing_label_for_target_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=LABELS[1:])
      with self.assertRaisesRegex(ValueError, "정확히 1개"):
        gold.run(**Kw)

  def test_duplicate_label_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=LABELS + [lab("a#s1", "개인")])
      with self.assertRaisesRegex(ValueError, "정확히 1개"):
        gold.run(**Kw)

  def test_label_on_lecture_note_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=LABELS + [lab("d#s1", "전사")])
      with self.assertRaisesRegex(ValueError, "Lecture Note"):
        gold.run(**Kw)

  def test_lecture_note_layer_not_whole_raises(self):
    Segs = [seg("d#s1", "d", "lecture_note", "팀", None) if s["segment_id"] == "d#s1" else s for s in SEGS]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Segs=Segs)
      with self.assertRaisesRegex(ValueError, "전사가 아니다"):
        gold.run(**Kw)

  def test_owner_not_in_list_with_team_gold_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Owners=["주인B"])
      with self.assertRaisesRegex(ValueError, "주인"):
        gold.run(**Kw)

  def test_unknown_layer_raises(self):
    Segs = [seg("a#s1", "a", "team_1jo", "공용", "주인A") if s["segment_id"] == "a#s1" else s for s in SEGS]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Segs=Segs)
      with self.assertRaisesRegex(ValueError, "layer"):
        gold.run(**Kw)

  def test_unknown_source_raises(self):
    Segs = [seg("a#s1", "a", "team_x", "개인", "주인A") if s["segment_id"] == "a#s1" else s for s in SEGS]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Segs=Segs)
      with self.assertRaisesRegex(ValueError, "source"):
        gold.run(**Kw)

  def test_unknown_intrinsic_layer_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=[lab("a#s1", "공용")] + LABELS[1:])
      with self.assertRaisesRegex(ValueError, "intrinsic_layer"):
        gold.run(**Kw)

  def test_label_outside_target_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Labels=LABELS + [lab("e#s1", "팀")])
      with self.assertRaisesRegex(ValueError, "대상 밖"):
        gold.run(**Kw)

  def test_team_group_not_all_1jo_raises(self):
    Segs = [seg("b#s1", "b", "team_1jo", "팀", "2조") if s["segment_id"] == "b#s1" else s for s in SEGS]
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d, Segs=Segs)
      with self.assertRaisesRegex(ValueError, "1조"):
        gold.run(**Kw)

  def test_missing_owner_list_raises(self):
    with tempfile.TemporaryDirectory() as d:
      Kw = make(d)
      with open(Kw["source_layers_path"], "w", encoding="utf-8") as f:
        json.dump({"purpose": "합성"}, f, ensure_ascii=False)
      with self.assertRaisesRegex(ValueError, "team_1jo_personal_owners"):
        gold.run(**Kw)

  def test_existing_output_raises_and_is_untouched(self):
    for Target in ("out_path", "report_path"):
      with self.subTest(Target=Target):
        with tempfile.TemporaryDirectory() as d:
          Kw = make(d)
          with open(Kw[Target], "w", encoding="utf-8") as f:
            f.write("기존")
          with self.assertRaisesRegex(ValueError, "이미 있다"):
            gold.run(**Kw)
          with open(Kw[Target], encoding="utf-8") as f:
            self.assertEqual(f.read(), "기존")


if __name__ == "__main__":
  unittest.main()
