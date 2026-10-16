import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from labeling.gold import group_for, read_owners
from retrieval.search import LAYER_ORDER
from runner.v2_sequential import DEFAULT_WORK_ROOT, REPO_DIR, _validate_out_dir, git_head_commit

# 사용자 결정 2026-10-17 빌드 필터 (A) : 공개 = 전사 층만
PUBLIC_LAYER = "전사"
# 노트 한 줄이 이 키를 다 갖지 않으면 층 · 링크를 정할 수 없다
_REQUIRED_KEYS = (
  "note_id", "layer", "group", "title", "body", "source_segment_ids", "upward_links", "downward_conditional_links",
)
# 파일 이름에 못 쓰는 문자는 _ 로 바꾼다 ( 경로 구분자 · 윈도 예약 문자 · 제어 문자 )
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# 노트 파일과 manifest 를 한 폴더에 섞으면 배포할 폴더 범위가 흐려진다
NOTES_SUBDIR = "notes"


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str) -> str:
  with open(path, "rb") as File:
    return hashlib.sha256(File.read()).hexdigest()


def read_vault(vault_path: str) -> list[dict]:
  Notes = []
  with open(vault_path, encoding="utf-8") as File:
    for LineNo, Line in enumerate(File, start=1):
      if not Line.strip():
        continue
      Row = json.loads(Line)
      Missing = [Key for Key in _REQUIRED_KEYS if not isinstance(Row, dict) or Key not in Row]
      if Missing:
        raise ValueError(f"vault.jsonl {LineNo}행에 없는 키: {Missing}")
      Notes.append(Row)
  ids = [Note["note_id"] for Note in Notes]
  # note_id 가 겹치면 링크 대상이 모호하다
  if len(set(ids)) != len(ids):
    raise ValueError("vault.jsonl 에 note_id 중복이 있다")
  for Note in Notes:
    # 층 순서 밖의 층은 공개 여부도 가시성도 정할 수 없다
    if Note["layer"] not in LAYER_ORDER:
      raise ValueError(f"알 수 없는 layer: {Note['layer']!r} ( {Note['note_id']} )")
  return Notes


def _file_name(note_id: str) -> str:
  Name = _UNSAFE_FILENAME_CHARS.sub("_", note_id)
  # 이 이름들은 폴더 자신이나 상위를 가리킨다
  if Name in ("", ".", ".."):
    raise ValueError(f"파일 이름으로 쓸 수 없는 note_id: {note_id!r}")
  return Name + ".md"


def _file_names(Notes: list[dict]) -> dict[str, str]:
  Names = {Note["note_id"]: _file_name(Note["note_id"]) for Note in Notes}
  # 치환 뒤 이름이 겹치면 한 노트가 다른 노트를 덮어쓴다
  if len(set(Names.values())) != len(Names):
    raise ValueError("파일 이름 치환 뒤 겹치는 note_id 가 있다")
  return Names


def _render_note(Note: dict, Body: str, UpwardIds: list[str], OpenedIds: list[str] | None) -> str:
  Lines = [
    f"# {Note['title']}",
    "",
    f"- note_id: {Note['note_id']}",
    f"- layer: {Note['layer']}",
    f"- source_segment_ids: {', '.join(Note['source_segment_ids'])}",
    "",
    Body,
    "",
    "## 상향 링크",
  ]
  Lines += [f"- [[{Id}]]" for Id in UpwardIds]
  # 공개 빌드는 조건부 링크 절 자체를 쓰지 않는다 ( None )
  if OpenedIds is not None:
    Lines += ["", "## 조건부 링크 ( 이 보기에서 열림 )"]
    Lines += [f"- [[{Id}]]" for Id in OpenedIds]
  return "\n".join(Lines) + "\n"


def _write_out(OutPath: str, Files: dict[str, str], ManifestName: str, Manifest: dict) -> None:
  os.makedirs(os.path.join(OutPath, NOTES_SUBDIR), exist_ok=False)
  for Name, Text in Files.items():
    # 같은 이름이 이미 있으면 덮어쓰지 않고 멈춘다
    with open(os.path.join(OutPath, NOTES_SUBDIR, Name), "x", encoding="utf-8") as File:
      File.write(Text)
  with open(os.path.join(OutPath, ManifestName), "x", encoding="utf-8") as File:
    json.dump(Manifest, File, ensure_ascii=False, indent=2)
    File.write("\n")


def _common_manifest(vault_path: str, Notes: list[dict], Included: list[dict], commit_fn, kind: str) -> dict:
  return {
    "kind": kind,
    "vault_path": os.path.abspath(vault_path),
    "vault_sha256": _sha256_file(vault_path),
    "harness_commit": commit_fn(),
    "notes_total": len(Notes),
    "notes_by_layer": {Layer: sum(1 for Note in Notes if Note["layer"] == Layer) for Layer in LAYER_ORDER},
    "notes_included": len(Included),
    "notes_excluded": len(Notes) - len(Included),
    "generated_at_utc": _utc_now(),
  }


def build_public(vault_path, out_dir, work_root=DEFAULT_WORK_ROOT, commit_fn=None, print_fn=print) -> dict:
  commit_fn = commit_fn or (lambda: git_head_commit(REPO_DIR))
  OutPath = _validate_out_dir(out_dir, work_root)
  Notes = read_vault(vault_path)
  Included = [Note for Note in Notes if Note["layer"] == PUBLIC_LAYER]
  IncludedIds = {Note["note_id"] for Note in Included}
  Names = _file_names(Included)
  Removed = 0
  Files = {}
  for Note in Included:
    # 사용자 결정 2026-10-17 빌드 필터 (A) : 공개본 밖을 가리키는 상향 링크는 깨진 링크이자 비공개 노트의 존재 노출이다
    for Target in Note["upward_links"]:
      if Target not in IncludedIds:
        raise ValueError(f"공개본에 없는 상향 링크 대상: {Note['note_id']} -> {Target}")
    # 사용자 결정 2026-10-17 빌드 필터 (A) : 하향 조건부 링크는 어떤 형태로도 쓰지 않고 수만 센다
    Removed += len(Note["downward_conditional_links"])
    Files[Names[Note["note_id"]]] = _render_note(Note, Note["body"], list(Note["upward_links"]), None)
  Manifest = _common_manifest(vault_path, Notes, Included, commit_fn, "public")
  # 공개 노트가 가진 하향 조건부 링크만 센다 - 제외된 노트의 링크는 공개본에 애초에 없었다
  Manifest["downward_conditional_links_removed"] = Removed
  _write_out(OutPath, Files, "build_manifest.json", Manifest)
  print_fn(
    f"public notes_total={Manifest['notes_total']} included={len(Included)} excluded={Manifest['notes_excluded']} "
    f"downward_removed={Removed}"
  )
  return Manifest


def visible_pairs(viewer_layer: str, viewer_group, owners: set) -> set:
  # 로컬 보기 (C′) : 보는 사람 층 이상인 층마다 group_for 로 그룹을 정한다 ( 가시 범위 확정 결정과 같은 규칙 )
  if viewer_layer not in LAYER_ORDER:
    raise ValueError(f"알 수 없는 viewer layer: {viewer_layer!r}")
  # 개인 · 팀 보기는 그룹이 없으면 아무 노트도 안 보이는 빈 보기가 조용히 만들어진다
  if viewer_layer == PUBLIC_LAYER and viewer_group is not None:
    raise ValueError("전사 보기는 viewer group 을 받지 않는다")
  if viewer_layer != PUBLIC_LAYER and not viewer_group:
    raise ValueError(f"{viewer_layer} 보기는 viewer group 이 필요하다")
  Seg = {"layer": viewer_layer, "group": viewer_group, "segment_id": "<viewer>"}
  return {(Layer, group_for(Seg, Layer, owners)) for Layer in LAYER_ORDER[LAYER_ORDER.index(viewer_layer):]}


def build_view(
  vault_path,
  source_layers_path,
  viewer_layer,
  viewer_group,
  out_dir,
  work_root=DEFAULT_WORK_ROOT,
  redact_body=False,
  commit_fn=None,
  print_fn=print,
) -> dict:
  commit_fn = commit_fn or (lambda: git_head_commit(REPO_DIR))
  OutPath = _validate_out_dir(out_dir, work_root)
  Owners = read_owners(source_layers_path)
  Pairs = visible_pairs(viewer_layer, viewer_group, Owners)
  Notes = read_vault(vault_path)
  AllIds = {Note["note_id"] for Note in Notes}
  Included = [Note for Note in Notes if (Note["layer"], Note["group"]) in Pairs]
  IncludedIds = {Note["note_id"] for Note in Included}
  Names = _file_names(Included)
  Opened = HiddenDown = HiddenUp = 0
  Files = {}
  for Note in Included:
    UpwardIds = []
    for Target in Note["upward_links"]:
      # 볼트에 아예 없는 대상은 가려진 것이 아니라 깨진 데이터다
      if Target not in AllIds:
        raise ValueError(f"볼트에 없는 상향 링크 대상: {Note['note_id']} -> {Target}")
      # 이 보기에 안 보이는 대상은 쓰지 않고 수만 센다 ( 정상 동작 )
      if Target in IncludedIds:
        UpwardIds.append(Target)
      else:
        HiddenUp += 1
    OpenedIds = []
    for Link in Note["downward_conditional_links"]:
      Target = Link["target_id"]
      if Target not in AllIds:
        raise ValueError(f"볼트에 없는 조건부 링크 대상: {Note['note_id']} -> {Target}")
      Condition = Link["visibility_condition"]
      if (Condition["layer"], Condition["group"]) in Pairs:
        OpenedIds.append(Target)
      else:
        HiddenDown += 1
    Opened += len(OpenedIds)
    # 발표 캡처에 팀원 문서 본문이 노출되지 않게 본문만 길이로 대신한다
    Body = f"( 본문 {len(Note['body'])}자 가림 )" if redact_body else Note["body"]
    Files[Names[Note["note_id"]]] = _render_note(Note, Body, UpwardIds, OpenedIds)
  Manifest = _common_manifest(vault_path, Notes, Included, commit_fn, "local_view")
  Manifest.update(
    {
      "source_layers_path": os.path.abspath(source_layers_path),
      "source_layers_sha256": _sha256_file(source_layers_path),
      "viewer": {"layer": viewer_layer, "group": viewer_group},
      "notes_written": len(Included),
      "conditional_links_opened": Opened,
      "conditional_links_hidden": HiddenDown,
      "upward_links_hidden": HiddenUp,
      "redact_body": bool(redact_body),
      # 조건부 링크가 열려 있어 배포하면 비공개 층 연결이 드러난다
      "do_not_deploy": True,
    }
  )
  _write_out(OutPath, Files, "view_manifest.json", Manifest)
  print_fn(
    f"view notes_total={Manifest['notes_total']} written={len(Included)} opened={Opened} hidden_down={HiddenDown} "
    f"hidden_up={HiddenUp}"
  )
  return Manifest


def parse_args(argv=None) -> argparse.Namespace:
  Parser = argparse.ArgumentParser(prog="python -m build.public_build")
  Sub = Parser.add_subparsers(dest="command", required=True)
  Public = Sub.add_parser("public", help="전사 층만 공개 빌드 ( 하향 조건부 링크 제거 )")
  Public.add_argument("--vault", required=True)
  Public.add_argument("--out-dir", required=True)
  View = Sub.add_parser("view", help="( 층, 그룹 ) 기준 로컬 보기 ( 배포 금지 )")
  View.add_argument("--vault", required=True)
  View.add_argument("--source-layers", required=True)
  View.add_argument("--viewer-layer", required=True)
  View.add_argument("--viewer-group", default=None, help="생략하면 그룹 없음 ( 전사 보기 )")
  View.add_argument("--out-dir", required=True)
  View.add_argument("--redact-body", action="store_true", help="본문 대신 글자 수만 쓴다")
  return Parser.parse_args(argv)


def main(argv=None) -> None:
  Args = parse_args(argv)
  if Args.command == "public":
    build_public(Args.vault, Args.out_dir)
  else:
    build_view(
      Args.vault, Args.source_layers, Args.viewer_layer, Args.viewer_group, Args.out_dir, redact_body=Args.redact_body
    )


if __name__ == "__main__":
  main()
