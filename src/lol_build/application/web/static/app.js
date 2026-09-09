"use strict";

const TEAM_SLOTS = { ally: ["ally1", "ally2", "ally3", "ally4"], enemy: ["enemy1", "enemy2", "enemy3", "enemy4"] };
const ALL_TEAM_SLOTS = [...TEAM_SLOTS.ally, ...TEAM_SLOTS.enemy];
const state = { catalog: null, mode: "recommend", dialogSide: null, actor: [], opponent: [] };
ALL_TEAM_SLOTS.forEach((slot) => { state[slot] = []; });
const $ = (selector) => document.querySelector(selector);

const metricLabels = {
  DAMAGE_TOTAL_8S: "8초 피해량",
  DAMAGE_FIRST_3S: "초반 피해량",
  ACTOR_END_HP_8S: "교전 후 체력",
  PHYSICAL_EHP: "물리 유효 체력",
  MAGICAL_EHP: "마법 유효 체력",
  MIXED_DAMAGE_EHP: "혼합 유효 체력",
  MIXED_EFFECTIVE_HEALTH: "혼합 유효 체력",
  CC_ADJUSTED_UPTIME: "CC 보정 가동률",
  ENGAGE_COMBAT_UPTIME_FRACTION: "교전 가동률",
  ENGAGE_DISTANCE_CLOSED_3S: "3초 접근 거리",
  LANE_RECOVERED_HP_30S: "30초 회복량",
  LANE_RECOVERY_30S: "30초 회복량",
  TOTAL_GOLD: "총 골드",
  HEARTSTEEL_PROC_COUNT: "강철심장 스택",
  ACTOR_SURVIVAL_MS_8S: "생존 시간",
  DORMANT_CORE_PASSIVE_TIME_MS: "패시브 비활성 시간",
};
const statLabels = {
  AD: "공격력", AP: "주문력", HP: "체력", ARMOR: "방어력",
  MAGIC_RESISTANCE: "마법 저항력", ATTACK_SPEED: "공격 속도",
  ABILITY_HASTE: "스킬 가속", MOVE_SPEED_FLAT: "이동 속도",
  MOVE_SPEED_PERCENT: "이동 속도", TENACITY: "강인함",
  CRITICAL_STRIKE_CHANCE: "치명타 확률", MANA: "마나",
  LIFESTEAL: "생명력 흡수", OMNIVAMP: "모든 피해 흡혈",
  BASE_HEALTH_REGEN_PERCENT: "체력 재생", FLAT_ARMOR_PENETRATION: "방어구 관통력",
  FLAT_MAGIC_PENETRATION: "마법 관통력", PERCENT_ARMOR_PENETRATION: "방어구 관통",
  PERCENT_MAGIC_PENETRATION: "마법 관통",
};
const statusLabels = {
  READY: "검증 완료", INSUFFICIENT_EVIDENCE: "근거 검증 중",
  NO_FEASIBLE_ITEM_RESPONSE: "조건 충족 빌드 없음", OUT_OF_SCOPE: "지원 범위 밖",
};
const championStatusMeta = {
  curated: { label: "완성·검증됨", suffix: "CURATED" },
  modeled_unverified: { label: "구현 완료·미검증", suffix: "UNVERIFIED" },
  wip: { label: "일부 메커니즘 미구현·진행 중", suffix: "WIP" },
  todo: { label: "미구현", suffix: "TODO" },
};
const axisStatusLabels = {
  FOUND: "빌드 발견", NO_FEASIBLE: "적격 빌드 없음",
  VERIFIED: "검증 완료", INSUFFICIENT_VERIFICATION: "근거 검증 중",
  IN_SCOPE: "범위 내", OUT_OF_SCOPE: "범위 밖",
};
const reasonLabels = {
  BALANCED_CHASSIS_GATED_DAMAGE_PRIORITY: "체급·접근 조건을 통과한 후보 중 8초 피해량이 가장 높았습니다.",
  BALANCED_FALLBACK_NO_FULL_CHASSIS: "모든 체급 조건을 만족한 후보가 없어 피해 손실 한도 안의 차선책을 골랐습니다.",
  OFFENSE_DAMAGE_PRIORITY: "최종 후보 중 8초 피해량과 교전 가동률을 우선했습니다.",
  DEFENSE_DURABILITY_WITH_DAMAGE_FLOOR: "피해량 하한을 통과한 후보 중 혼합 유효 체력을 우선했습니다.",
  DEFENSE_FALLBACK_NO_FULL_CHASSIS: "모든 체급 조건을 만족한 후보가 없어 전체 후보 중 생존 지표를 우선했습니다.",
  DEFENSE_FALLBACK_NO_DAMAGE_FLOOR_MET: "체급 조건을 통과했지만 피해량 하한을 넘긴 후보가 없어 하한 없이 생존 지표를 우선했습니다.",
  KILL_GATE_AND_CHASSIS_PASSED: "처치 문턱과 전 코어 체급·진입 조건을 함께 통과했습니다.",
  CHASSIS_PASSED_KILL_FALLBACK: "처치 문턱을 넘긴 후보가 없어 전 코어 체급 조건을 통과한 후보를 골랐습니다.",
  KILL_GATE_PASSED_CHASSIS_FALLBACK: "체급 조건을 모두 만족하지 못했지만 처치 문턱을 통과한 후보를 골랐습니다.",
  DAMAGE_FALLBACK_NO_KILL_OR_CHASSIS: "처치·체급 조건을 모두 통과한 후보가 없어 초반 피해량 기준으로 선택했습니다.",
  KILL_THRESHOLD_DAMAGE_PRIORITY: "처치 문턱을 통과한 후보 중 8초 피해량이 가장 높았습니다.",
  EARLY_DAMAGE_KILL_FALLBACK: "처치 문턱을 넘긴 후보가 없어 초반 3초 피해량을 우선했습니다.",
  DEFENSE_WITH_PRIMARY_DAMAGE_LOSS_LIMIT: "허용된 공격력 손실 안에서 체급·유지력·진입 능력을 우선했습니다.",
};
const slotExclusionLabels = {
  ALL_CORE_ENGAGE_READY_NOT_MET: "이 아이템으로 바꾸면 일부 코어에서 교전 진입 조건을 만족하지 못합니다",
  ALL_CORE_CHASSIS_READY_NOT_MET: "이 아이템으로 바꾸면 일부 코어에서 최소 체급 조건을 만족하지 못합니다",
  ALL_CORE_ITEM_PASSIVES_READY_NOT_MET: "이 아이템으로 바꾸면 일부 코어에서 핵심 패시브가 활성화되지 않습니다",
  DEFENSE_DAMAGE_FLOOR_NOT_MET: "이 아이템으로 바꾸면 방어 분기의 피해량 하한을 벗어납니다",
};
const constraintLabels = {
  ALL_CORE_ENGAGE_READY: "1~3코어 모두 교전 진입 가능",
  ALL_CORE_CHASSIS_READY: "1~3코어 모두 최소 체급 충족",
  ALL_CORE_ITEM_PASSIVES_READY: "1~3코어 모두 핵심 패시브 활성",
  PRIMARY_DAMAGE_FLOOR_PASSED: "분기 피해량 하한 통과",
  PRIMARY_DAMAGE_LOSS_LIMIT_PASSED: "허용 피해 손실 한도 통과",
  NO_DORMANT_CORE_PASSIVE: "완성 시점부터 핵심 패시브 활성",
  KILL_THRESHOLD_PASSED: "처치 문턱 통과",
  KILL_THRESHOLD_NOT_MET: "처치 문턱 미달 · fallback 적용",
};
const roleLabels = {
  DAMAGE_OUTPUT: "공격력", DAMAGE_EFFECT: "추가 피해", ATTACK_CADENCE: "평타 빈도",
  ABILITY_CADENCE: "스킬 회전", HEALTH_CHASSIS: "기본 체급", PHYSICAL_DURABILITY: "물리 내구력",
  MAGICAL_DURABILITY: "마법 내구력", ENGAGE_MOBILITY: "접근·추격", CC_DURATION_REDUCTION: "CC 지속시간 감소",
  COMBAT_SUSTAIN: "교전 유지력", PHYSICAL_PENETRATION: "방어력 관통", MAGICAL_PENETRATION: "마법 관통",
  ITEM_ACTIVE: "사용 효과", LOW_HEALTH_SURVIVAL: "저체력 생존", STACKING_HEALTH_SCALING: "누적 체력 성장",
  OUT_OF_COMBAT_RECOVERY: "비전투 회복", BONUS_HEALTH_REQUIREMENT: "추가 체력 조건",
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function initials(name) {
  return name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function itemById(id) {
  return state.catalog.items.find((item) => item.id === Number(id));
}

function championByKey(key) {
  return state.catalog.champions.find((champion) => champion.key === key);
}

function icon(item, extraClass = "") {
  if (!item?.icon) return `<span class="item-icon ${extraClass}">${escapeHtml(initials(item?.name || "?"))}</span>`;
  const { url, column, row, columns, rows } = item.icon;
  const x = columns > 1 ? column / (columns - 1) * 100 : 0;
  const y = rows > 1 ? row / (rows - 1) * 100 : 0;
  const style = `background-image:url('${url}');background-size:${columns * 100}% ${rows * 100}%;background-position:${x}% ${y}%`;
  return `<span class="item-icon ${extraClass}" style="${style}" role="img" aria-label="${escapeHtml(item.name)}"></span>`;
}

function championName(side) {
  const select = $(`#${side}Select`);
  return championByKey(select.value)?.name || select.options[select.selectedIndex]?.text || select.value;
}

function number(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("ko-KR", { maximumFractionDigits: digits }) : "—";
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const envelope = await response.json();
  if (!response.ok || !envelope.ok) throw new Error(envelope.error?.message || "요청에 실패했습니다.");
  return envelope.data;
}

// TODO 상태(미구현 — 기본 공격 폴백뿐)는 선택 목록에서 숨긴다.
const CHAMPION_STATUS_ORDER = ["curated", "modeled_unverified", "wip"];

function fillChampionSelect(select, preferred, optional = false) {
  const blank = optional ? `<option value="">— 비어 있음 —</option>` : "";
  const groups = CHAMPION_STATUS_ORDER.map((status) => {
    const champions = state.catalog.champions.filter((champion) => champion.status === status);
    if (!champions.length) return "";
    const meta = championStatusMeta[status];
    const options = champions.map((champion) =>
      `<option value="${escapeHtml(champion.key)}" class="status-${status}">${escapeHtml(champion.name)}</option>`
    ).join("");
    return `<optgroup label="${meta ? meta.suffix : status.toUpperCase()}">${options}</optgroup>`;
  }).join("");
  select.innerHTML = blank + groups;
  if (state.catalog.champions.some((champion) => champion.key === preferred)) select.value = preferred;
  else if (optional) select.value = "";
}

function updateChampionStatus(side) {
  const badge = $(`#${side}Status`);
  if (!badge) return;
  const champion = championByKey($(`#${side}Select`).value);
  const meta = champion && championStatusMeta[champion.status];
  badge.className = meta ? `champion-status status-${champion.status}` : "champion-status";
  badge.textContent = meta ? meta.suffix : "";
  badge.title = meta ? `${champion.name} · ${meta.label}` : "";
}

function buildTeamSlots() {
  const render = (columnId, slots, label) => {
    $(`#${columnId}`).insertAdjacentHTML("beforeend", slots.map((slot, index) =>
      `<div class="team-slot empty" id="${slot}Slot">
        <label class="field-label" for="${slot}Select">${label} ${index + 2}</label>
        <div class="champion-select-wrap">
          <select id="${slot}Select" aria-label="${label} ${index + 2}"></select>
          <span class="champion-status" id="${slot}Status"></span>
        </div>
        <div class="item-section">
          <div class="item-heading"><span>아이템</span><small id="${slot}ItemCount">0 / 3</small></div>
          <div class="selected-items" id="${slot}Items"></div>
          <button type="button" class="add-item" data-side="${slot}">＋ 아이템 추가</button>
        </div>
      </div>`
    ).join(""));
  };
  render("allyColumn", TEAM_SLOTS.ally, "아군");
  render("enemyColumn", TEAM_SLOTS.enemy, "상대");
  ALL_TEAM_SLOTS.forEach((slot) => {
    fillChampionSelect($(`#${slot}Select`), null, true);
    $(`#${slot}Select`).addEventListener("change", () => onTeamSlotChange(slot));
    $(`.add-item[data-side="${slot}"]`).addEventListener("click", () => openItemDialog(slot));
    renderSelected(slot);
    onTeamSlotChange(slot);
  });
}

function slotIsActive(slot) {
  return Boolean($(`#${slot}Select`).value);
}

function onTeamSlotChange(slot) {
  const active = slotIsActive(slot);
  $(`#${slot}Slot`).classList.toggle("empty", !active);
  if (!active) {
    state[slot] = [];
    renderSelected(slot);
  }
  updateChampionStatus(slot);
  updateTeamSummary();
}

function updateTeamSummary() {
  const allies = TEAM_SLOTS.ally.filter(slotIsActive).length;
  const enemies = TEAM_SLOTS.enemy.filter(slotIsActive).length;
  $("#teamSummary").textContent = `${allies + 1} vs ${enemies + 1}`;
}

function teamPayload(slots) {
  return slots.filter(slotIsActive).map((slot) => ({
    champion: $(`#${slot}Select`).value,
    item_ids: state[slot],
  }));
}

function updateChampionGlyph(side) {
  const select = $(`#${side}Select`);
  $(`#${side}Glyph`).textContent = initials(championByKey(select.value)?.name || "?");
  updateChampionStatus(side);
}

function renderSelected(side) {
  const values = state[side];
  const target = $(`#${side}Items`);
  $(`#${side}ItemCount`).textContent = `${values.length} / 3`;
  if (!values.length) {
    target.innerHTML = `<div class="empty-items">선택한 아이템 없음</div>`;
    return;
  }
  target.innerHTML = values.map((id) => {
    const item = itemById(id);
    return `<div class="item-chip">${icon(item)}<span title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span><button class="remove-item" data-side="${side}" data-id="${id}" aria-label="${escapeHtml(item.name)} 제거">×</button></div>`;
  }).join("");
}

function openItemDialog(side) {
  if (state[side].length >= 3) return toast("최대 3코어까지 선택할 수 있습니다.");
  state.dialogSide = side;
  $("#itemSearch").value = "";
  renderItemOptions("");
  $("#itemDialog").showModal();
  setTimeout(() => $("#itemSearch").focus(), 30);
}

function renderItemOptions(query) {
  const normalized = query.trim().toLowerCase();
  const selected = new Set(state[state.dialogSide] || []);
  const items = state.catalog.items.filter((item) => !selected.has(item.id) && (
    !normalized || item.name.toLowerCase().includes(normalized) || String(item.id).includes(normalized)
  )).slice(0, 100);
  $("#itemResults").innerHTML = items.map((item) =>
    `<button type="button" class="item-option" data-id="${item.id}">${icon(item)}<span class="meta"><strong>${escapeHtml(item.name)}</strong><small>${number(item.cost, 0)} 골드 · ${escapeHtml(item.stats.slice(0, 3).map((stat) => statLabels[stat] || stat).join(" · ") || "고유 효과")}</small></span></button>`
  ).join("") || `<div class="empty-items">검색 결과가 없습니다.</div>`;
}

function payload() {
  return {
    actor: $("#actorSelect").value,
    opponent: $("#opponentSelect").value,
    actor_item_ids: state.mode === "evaluate" ? state.actor : [],
    opponent_item_ids: state.opponent,
    level: Number($("#levelInput").value),
    duration_ms: Math.round(Number($("#durationInput").value) * 1000),
    horizon_ms: Math.round(Number($("#horizonInput").value) * 1000),
    allies: teamPayload(TEAM_SLOTS.ally),
    additional_opponents: teamPayload(TEAM_SLOTS.enemy),
  };
}

function collectBlockers(data) {
  const recommendation = data.recommendation || {};
  return [...new Set([...(data.blockers || []), ...(recommendation.blockers || [])])].sort();
}

function buildPath(ids) {
  return ids.map((id, index) => {
    const item = itemById(id) || { name: `Item ${id}` };
    const arrow = index ? `<span class="path-arrow">›</span>` : "";
    return `${arrow}<div class="build-item">${icon(item)}<span title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span></div>`;
  }).join("");
}

function metricRows(metrics) {
  const prioritized = Object.entries(metrics || {}).filter(([key]) => metricLabels[key]).slice(0, 6);
  return prioritized.map(([key, value]) => {
    const suffix = key.includes("FRACTION") || key.includes("UPTIME") ? "%" : "";
    const display = suffix ? number(Number(value) * 100) : number(value);
    return `<div class="metric-row"><span>${metricLabels[key]}</span><b>${display}${suffix}</b></div>`;
  }).join("");
}

function metricComparisonRows(comparisons) {
  return (comparisons || []).map((comparison) => {
    const delta = Number(comparison.delta);
    const direction = comparison.objective === "MINIMIZE" ? "낮을수록 유리" : "높을수록 유리";
    const signed = delta > 0 ? `+${number(delta)}` : number(delta);
    return `<div class="comparison-row"><span>${escapeHtml(metricLabels[comparison.metric_id] || comparison.metric_id)}<small>${direction}</small></span><b>${signed}</b></div>`;
  }).join("");
}

function renderSlotRunnerUp(slotRunnerUp) {
  if (!slotRunnerUp) return "";
  if (slotRunnerUp.item_id == null) {
    const legalCount = slotRunnerUp.legal_alternative_count ?? 0;
    if (legalCount === 0) {
      return `<div class="slot-runner-up none">경쟁 후보 없음 · 이 자리를 채울 다른 아이템이 없었습니다</div>`;
    }
    const excludedId = slotRunnerUp.excluded_item_id;
    if (excludedId == null) {
      return `<div class="slot-runner-up none">대체 가능한 아이템 ${number(legalCount, 0)}개를 시도했지만 이 분기의 조건을 만족하는 대안이 없었습니다 — 이 아이템이 조건을 만족하는 유일한 선택이었습니다</div>`;
    }
    const excludedItem = itemById(excludedId) || { name: `Item ${excludedId}` };
    const reasons = (slotRunnerUp.excluded_reason_codes || [])
      .map((code) => `<li>${escapeHtml(slotExclusionLabels[code] || code)}</li>`)
      .join("");
    return `<details class="slot-runner-up excluded"><summary>대체 가능한 아이템 ${number(legalCount, 0)}개 중 이 분기 조건을 넘긴 게 없음 · 가장 근접한 후보 · ${escapeHtml(excludedItem.name)}</summary><div class="slot-runner-up-body">${icon(excludedItem)}<div><ul class="reason-list">${reasons}</ul><div class="comparison-list">${metricComparisonRows(slotRunnerUp.excluded_metric_comparisons)}</div></div></div></details>`;
  }
  const item = itemById(slotRunnerUp.item_id) || { name: `Item ${slotRunnerUp.item_id}` };
  const count = number(slotRunnerUp.alternative_count, 0);
  return `<details class="slot-runner-up"><summary>2위 후보 · ${escapeHtml(item.name)} (경쟁 ${count}개)</summary><div class="slot-runner-up-body">${icon(item)}<div class="comparison-list">${metricComparisonRows(slotRunnerUp.metric_comparisons)}</div></div></details>`;
}

function renderExplanation(branch) {
  const explanation = branch.explanation;
  if (!explanation) return "";
  const reasons = (explanation.reason_codes || []).map((code) =>
    `<li>${escapeHtml(reasonLabels[code] || code)}</li>`
  ).join("");
  const constraints = (explanation.satisfied_constraints || []).map((code) =>
    `<span>${escapeHtml(constraintLabels[code] || code)}</span>`
  ).join("");
  const contributions = (explanation.item_contributions || []).map((contribution) => {
    const item = itemById(contribution.item_id) || { name: `Item ${contribution.item_id}` };
    const roles = (contribution.role_codes || []).map((code) => roleLabels[code] || code).join(" · ");
    return `<div class="item-reason">${icon(item)}<div><b>${escapeHtml(item.name)}</b><small>${escapeHtml(roles || "정적 스탯 기여")}</small>${renderSlotRunnerUp(contribution.slot_runner_up)}</div></div>`;
  }).join("");
  const comparisons = metricComparisonRows(explanation.metric_comparisons);
  const reference = explanation.comparison_item_ids?.length
    ? `<div class="comparison-build"><span>비교안</span><div>${buildPath(explanation.comparison_item_ids)}</div></div>`
    : "";
  return `<details class="explanation"><summary>왜 이 빌드인가?</summary><div class="explanation-body"><ul class="reason-list">${reasons}</ul><div class="constraint-list">${constraints}</div><h4>아이템별 역할</h4><div class="item-reasons">${contributions}</div>${reference}${comparisons ? `<div class="comparison-list">${comparisons}</div>` : ""}<code>${escapeHtml(explanation.policy_id)}</code></div></details>`;
}

function renderRecommendation(data) {
  const recommendation = data.recommendation;
  if (!recommendation) throw new Error("이 챔피언의 추천 모델이 아직 등록되지 않았습니다.");
  const branches = recommendation.branches || {};
  const definitions = [
    ["DEFAULT", "균형 빌드", "DEFAULT", true],
    ["OFFENSE", "공격 분기", "OFFENSE", false],
    ["DEFENSE", "방어 분기", "DEFENSE", false],
  ];
  $("#resultTitle").textContent = `${championName("actor")} 추천 빌드`;
  const legacyStatus = recommendation.recommendation_status || "INSUFFICIENT_EVIDENCE";
  const stateLabels = recommendation.state
    ? [recommendation.state.outcome, recommendation.state.verification, recommendation.state.scope].map((value) => axisStatusLabels[value] || value)
    : [statusLabels[legacyStatus] || legacyStatus];
  $("#resultStatus").textContent = stateLabels.join(" · ");
  const assumption = recommendation.assumptions?.game_state === "NOT_MODELED"
    ? `<aside class="assumption-notice"><b>게임 상태는 계산하지 않았습니다.</b><span>양측 레벨 ${escapeHtml(String(recommendation.assumptions.level_assumption || "").replace("EQUAL_LEVEL_", ""))}을 가정합니다. 현재 골드·경험치 격차가 있다면 방어 분기를 포함해 다시 검토하세요.</span></aside>`
    : "";
  $("#resultBody").innerHTML = `${assumption}<div class="branch-grid">${definitions.map(([id, title, kicker, primary]) => {
    const branch = branches[id];
    if (!branch) return "";
    return `<article class="branch-card branch-${id.toLowerCase()} ${primary ? "primary" : ""}"><span class="branch-kicker">${kicker}</span><h3>${title}</h3><div class="build-path">${buildPath(branch.item_ids || [])}</div><div class="metric-list">${metricRows(branch.metrics)}</div>${renderExplanation(branch)}</article>`;
  }).join("")}</div>`;
}

function renderEvaluation(data) {
  const actor = championName("actor");
  const opponent = championName("opponent");
  const actorLost = Number(data.actor_hp_lost);
  const opponentLost = Number(data.opponent_hp_lost);
  const scale = Math.max(actorLost, opponentLost, 1);
  $("#resultTitle").textContent = `${actor} vs ${opponent}`;
  $("#resultStatus").textContent = data.timeline?.target_dead_at_horizon ? "KILL THRESHOLD MET" : "SIMULATED";
  $("#resultBody").innerHTML = `<article class="duel-card panel"><div class="duel-score"><div class="duel-side"><span class="branch-kicker">${escapeHtml(actor)}</span><h3>받은 피해</h3><div class="damage-number actor-damage">${number(actorLost)}</div><progress class="bar actor-damage" max="${scale}" value="${actorLost}"></progress><p class="model-line">${escapeHtml(data.actor_action_model)}</p></div><div class="duel-vs">VS</div><div class="duel-side"><span class="branch-kicker">${escapeHtml(opponent)}</span><h3>받은 피해</h3><div class="damage-number opponent-damage">${number(opponentLost)}</div><progress class="bar opponent-damage" max="${scale}" value="${opponentLost}"></progress><p class="model-line">${escapeHtml(data.opponent_action_model)}</p></div></div><div class="timeline-summary"><div class="summary-cell"><span>초반 상대 피해</span><b>${number(data.timeline?.damage_to_target_first_horizon)}</b></div><div class="summary-cell"><span>전체 상대 피해</span><b>${number(data.timeline?.damage_to_target_total)}</b></div><div class="summary-cell"><span>처리 이벤트</span><b>${number(data.timeline?.log?.length, 0)}</b></div></div></article>`;
}

function renderBlockers(blockers) {
  $("#blockerCount").textContent = blockers.length;
  $("#blockerList").innerHTML = blockers.length
    ? blockers.map((blocker) => `<li>${escapeHtml(blocker)}</li>`).join("")
    : "<li>현재 입력에 대한 추가 blocker가 없습니다.</li>";
  $("#blockerPanel").open = blockers.length > 0 && blockers.length <= 5;
}

async function run() {
  const button = $("#runButton");
  const requestPayload = payload();
  const requestKind = state.mode === "recommend" ? "후보 빌드" : "교전 타임라인";
  const startedAt = performance.now();
  button.disabled = true;
  button.classList.add("loading");
  $(".button-label").textContent = state.mode === "recommend" ? "후보 빌드 계산 중…" : "교전 타임라인 계산 중…";
  $(".button-arrow").textContent = "◌";
  console.info(`[Rift Foundry] ${requestKind} 계산 요청`, requestPayload);
  try {
    const data = await api(state.mode === "recommend" ? "/api/recommend" : "/api/evaluate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestPayload),
    });
    if (state.mode === "recommend") renderRecommendation(data); else renderEvaluation(data);
    renderBlockers(collectBlockers(data));
    $("#results").classList.remove("hidden");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
    console.info(`[Rift Foundry] ${requestKind} 계산 완료 · ${((performance.now() - startedAt) / 1000).toFixed(2)}초`);
  } catch (error) {
    console.error(`[Rift Foundry] ${requestKind} 계산 실패`, error);
    toast(error.message || "계산에 실패했습니다.");
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    $(".button-label").textContent = state.mode === "recommend" ? "빌드 계산 시작" : "교전 시뮬레이션 시작";
    $(".button-arrow").textContent = "→";
  }
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.add("hidden"), 3500);
}

function bind() {
  document.querySelectorAll(".mode-tab").forEach((button) => button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    document.body.classList.toggle("recommend-mode", state.mode === "recommend");
    document.querySelectorAll(".mode-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    $(".button-label").textContent = state.mode === "recommend" ? "빌드 계산 시작" : "교전 시뮬레이션 시작";
    $("#runNote").textContent = state.mode === "recommend" ? "추천은 후보 경로 전체를 계산하므로 수십 초가 걸릴 수 있습니다." : "양쪽 현재 아이템과 행동 모델로 8초 타임라인을 계산합니다.";
  }));
  ["actor", "opponent"].forEach((side) => {
    $(`#${side}Select`).addEventListener("change", () => updateChampionGlyph(side));
    $(`.add-item[data-side="${side}"]`).addEventListener("click", () => openItemDialog(side));
  });
  $("#swapButton").addEventListener("click", () => {
    const actor = $("#actorSelect").value;
    $("#actorSelect").value = $("#opponentSelect").value;
    $("#opponentSelect").value = actor;
    [state.actor, state.opponent] = [state.opponent, state.actor];
    ["actor", "opponent"].forEach((side) => { updateChampionGlyph(side); renderSelected(side); });
  });
  $("#itemSearch").addEventListener("input", (event) => renderItemOptions(event.target.value));
  $("#itemResults").addEventListener("click", (event) => {
    const option = event.target.closest(".item-option");
    if (!option) return;
    state[state.dialogSide].push(Number(option.dataset.id));
    renderSelected(state.dialogSide);
    $("#itemDialog").close();
  });
  document.addEventListener("click", (event) => {
    const remove = event.target.closest(".remove-item");
    if (!remove) return;
    state[remove.dataset.side] = state[remove.dataset.side].filter((id) => id !== Number(remove.dataset.id));
    renderSelected(remove.dataset.side);
  });
  $("#runButton").addEventListener("click", run);
}

async function boot() {
  try {
    state.catalog = await api("/api/catalog");
    $("#patchBadge").textContent = `PATCH ${state.catalog.patch}`;
    fillChampionSelect($("#actorSelect"), "Darius");
    fillChampionSelect($("#opponentSelect"), "Garen");
    buildTeamSlots();
    ["actor", "opponent"].forEach((side) => { updateChampionGlyph(side); renderSelected(side); });
    bind();
  } catch (error) {
    toast(`로컬 엔진을 불러오지 못했습니다: ${error.message}`);
  }
}

boot();
