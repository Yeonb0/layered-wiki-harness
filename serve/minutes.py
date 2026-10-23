# 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 문서는 합성 시연 코퍼스 차수 901. 시연 작업 폴더에만 쓰고 실험 코퍼스 · 평가 집계에 넣지 않는다 ( 3절 24 · 25 )
import collections
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime

from agent.types import SourceDoc, SourceSegment
from segmentation.segment import process_doc

SNAPSHOT = 901
FILE_NAME = "minutes_901.json"
DOC_STATUS = ("running", "awaiting_approval", "decided", "failed")
TEXT_MAX_CHARS = 20000
_EMPTY = {"version": 1, "docs": []}


class ConflictError(Exception):
  # 상태가 맞지 않아 지금은 할 수 없는 요청 - 409 로 돌려준다
  pass


def segment_text(raw_text: str) -> list:
  # 세그먼트 규칙 v1.1 은 segmentation/segment.py 의 process_doc 를 그대로 부른다 - 규칙을 여기에 다시 쓰지 않는다 ( Prop_keys 는 빈 집합 )
  _, _, Segs = process_doc(raw_text, set(), collections.Counter())
  if not Segs:
    raise ValueError("규칙 v1.1 로 나눈 세그먼트가 0개다")
  return Segs


def segment_rows(doc_id: str, Segs: list) -> list:
  # segment.py run() 의 변환과 같다 : 텍스트는 줄 원문을 "\n" 으로 잇고 seq 는 1 부터, segment_id 는 doc_id#s순번
  return [
    {"segment_id": f"{doc_id}#s{Seq}", "seq": Seq, "text": "\n".join(Text for _, Text in Seg)}
    for Seq, Seg in enumerate(Segs, 1)
  ]


def source_doc_of(Record: dict) -> SourceDoc:
  # runner.v2_sequential.load_source_docs 가 만드는 SourceDoc 과 같은 필드다 ( 정의 : agent/types.py )
  # 팀 회의 : 층 팀 · 그룹 팀 이름 / 전사 회의 : 전사 · None - source_team 은 항상 None 이다
  return SourceDoc(
    doc_id=Record["doc_id"],
    title=Record["title"],
    source_layer=Record["source_layer"],
    source_group=Record["source_group"],
    segments=[SourceSegment(segment_id=S["segment_id"], seq=S["seq"], text=S["text"]) for S in Record["segments"]],
    # 실험 경로 load_source_docs 와 같은 모양 - 개인이 아닌 문서에는 team 을 두지 않는다 ( 채팅 Claude 보정 1 의 오류 정정 )
    source_team=None,
  )


class MinutesStore:
  def __init__(self, dir_path) -> None:
    self.dir_path = dir_path
    self.path = os.path.join(dir_path, FILE_NAME)
    self.lock = threading.Lock()
    os.makedirs(dir_path, exist_ok=True)
    if not os.path.exists(self.path):
      self.data = json.loads(json.dumps(_EMPTY))
      self._save()
    else:
      try:
        with open(self.path, encoding="utf-8") as File:
          self.data = json.load(File)
      except json.JSONDecodeError as Error:
        # 깨진 파일을 비어 있는 것으로 보고 덮어쓰면 기록이 사라진다
        raise ValueError(f"회의록 파일의 JSON 이 깨졌다: {self.path} ( {Error} )") from None
    self._check_loaded()

  def _save(self) -> None:
    descriptor, temp = tempfile.mkstemp(dir=self.dir_path, suffix=".tmp")
    try:
      with os.fdopen(descriptor, "w", encoding="utf-8") as File:
        json.dump(self.data, File, ensure_ascii=False, indent=2)
        File.write("\n")
        File.flush()
        os.fsync(File.fileno())
      os.replace(temp, self.path)
    except BaseException:
      if os.path.exists(temp):
        os.remove(temp)
      raise

  def _check_loaded(self) -> None:
    if not isinstance(self.data, dict) or self.data.get("version") != 1 or not isinstance(self.data.get("docs"), list):
      raise ValueError("회의록 파일의 구조가 맞지 않는다 ( version 1, docs 목록 )")
    Ids = []
    for Doc in self.data["docs"]:
      if not isinstance(Doc, dict) or Doc.get("snapshot") != SNAPSHOT or Doc.get("status") not in DOC_STATUS:
        raise ValueError("회의록 파일의 항목이 차수 901 형식이 아니다")
      Ids.append(Doc["doc_id"])
    if len(set(Ids)) != len(Ids):
      raise ValueError("회의록 파일에 doc_id 중복이 있다")

  def docs(self) -> list:
    with self.lock:
      return json.loads(json.dumps(self.data["docs"]))

  def get(self, doc_id: str):
    with self.lock:
      for Doc in self.data["docs"]:
        if Doc["doc_id"] == doc_id:
          return json.loads(json.dumps(Doc))
    return None

  def create(self, meeting: dict, mode: str, text: str, submitted_by: str, now: datetime) -> dict:
    with self.lock:
      Segs = segment_text(text)
      DocId = f"{SNAPSHOT}{len(self.data['docs']) + 1:029d}"
      Record = {
        "doc_id": DocId, "snapshot": SNAPSHOT, "meeting_id": meeting["meeting_id"], "mode": mode, "title": meeting["title"],
        "raw_text": text, "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "segments": segment_rows(DocId, Segs),
        "source_layer": meeting["workspace"]["layer"], "source_group": meeting["workspace"]["group"],
        "submitted_by": submitted_by, "submitted_at": now.strftime("%Y-%m-%dT%H:%M"), "job_id": None, "status": "running",
        "error": None, "request_dir": None, "note_count": 0, "decisions": {}, "approved_notes": [], "approved_links_dropped": 0,
      }
      self.data["docs"].append(Record)
      self._save()
      return json.loads(json.dumps(Record))

  def update(self, doc_id: str, **fields) -> dict:
    with self.lock:
      for Doc in self.data["docs"]:
        if Doc["doc_id"] == doc_id:
          if "status" in fields and fields["status"] not in DOC_STATUS:
            raise ValueError(f"알 수 없는 status: {fields['status']!r}")
          Doc.update(fields)
          self._save()
          return json.loads(json.dumps(Doc))
    raise KeyError(doc_id)
