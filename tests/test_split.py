"""파일럿 · 본실험 분리 테스트

아래 문서 · 이름 · title 은 전부 합성 픽스처일 뿐이며 규칙과 무관하다
"""
import unittest

from segmentation import split as sp


def doc(i, path, source, layer, group, title=None, n=1):
  return {"doc_id": i, "path": path, "source": source, "layer": layer, "group": group, "title": title or i, "n_segments": n}


A, B, C, D, E, F, G = ("a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32, "f" * 32, "1" * 32)

DOCS = [
  doc(A, f"1조 {A}.md", "team_1jo", "팀", "1조"),
  doc(B, f"1조/갑 {B}.md", "team_1jo", "개인", "갑"),
  doc(C, f"1조/갑/생각 {C}.md", "team_1jo", "개인", "갑"),
  doc(D, f"1조/갑/생각/세부 {D}.md", "team_1jo", "개인", "갑"),
  doc(E, f"1조/회의록/1차 {E}.md", "team_1jo", "팀", "1조"),
  doc("att-0000000000000000", "1조/회의록/1차/Q.md", "team_1jo", "팀", "1조"),
  doc(F, f"1조/산출물 {F}.md", "team_1jo", "팀", "1조"),
  doc(G, f"1조/산출물/하위 {G}.md", "team_1jo", "팀", "1조"),
]


class TestUnits(unittest.TestCase):
  def test_unit_roots(self):
    R = sp.unit_roots(DOCS)
    self.assertEqual(R[A], A)
    self.assertEqual(R[B], B)
    self.assertEqual(R[C], C)
    self.assertEqual(R[D], C)
    self.assertEqual(R["att-0000000000000000"], E)
    self.assertEqual(R[G], F)

  def test_pilot_count(self):
    self.assertEqual([sp.pilot_count(n) for n in (1, 2, 6, 18, 46)], [0, 1, 1, 3, 7])

  def test_units_never_split_and_seed_is_deterministic(self):
    Assign1, _, _, _ = sp.split(DOCS, 7)
    Assign2, _, _, _ = sp.split(DOCS, 7)
    self.assertEqual(Assign1, Assign2)
    self.assertEqual(Assign1[C], Assign1[D])
    self.assertEqual(Assign1[E], Assign1["att-0000000000000000"])
    self.assertEqual(Assign1[F], Assign1[G])

  def test_same_title_across_splits_raises(self):
    Docs = [doc(str(i) * 32, f"L/p{i} {str(i) * 32}.md", "lecture_note", "전사", None, title="같음") for i in range(1, 10)]
    with self.assertRaises(ValueError):
      sp.split(Docs, 1)

  def test_mixed_stratum_unit_raises(self):
    Docs = [doc(F, f"1조/산출물 {F}.md", "team_1jo", "팀", "1조"), doc(G, f"1조/산출물/하위 {G}.md", "team_1jo", "개인", "갑")]
    with self.assertRaises(ValueError):
      sp.split(Docs, 1)


if __name__ == "__main__":
  unittest.main()
