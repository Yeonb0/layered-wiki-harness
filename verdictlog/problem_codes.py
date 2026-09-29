# client/validation.py 가 만드는 problem 코드 전부를 스키마 오류 / 모드 규칙 무효 / 결정 위반 세 분류로 매핑한다
# 워크플로 실패는 problem 코드가 아니라 ok=false 로 판정되므로 여기 없다
PROBLEM_CODE_CLASSIFICATION = {
  "ok_not_boolean": "schema_error",
  "errors_not_string_list": "schema_error",
  "log_not_string": "schema_error",
  "verdict_not_object": "schema_error",
  "layer_missing_or_not_string": "schema_error",
  "layer_not_recognized": "schema_error",
  "upward_links_invalid": "schema_error",
  "downward_conditional_links_invalid": "schema_error",
  "downward_conditional_link_item_invalid": "schema_error",
  "upward_link_target_not_in_candidates": "schema_error",
  "downward_link_target_not_in_candidates": "schema_error",
  "rationale_missing_or_not_string": "schema_error",
  "layer_above_source_under_split_by_layer": "mode_rule_rejection",
  "layer_below_source": "decision_violation",
  "upward_link_target_below_verdict_layer": "decision_violation",
  "downward_link_target_same_layer": "decision_violation",
}
