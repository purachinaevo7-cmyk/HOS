(() => {
  "use strict";

  const state = {
    reviews: [],
    summary: null,
    query: "",
    minScore: 0,
    tag: "all",
    sort: "latest",
  };

  const $ = (selector) => document.querySelector(selector);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function activityDate(review) {
    return review.visited_at || (review.logged_at || "").slice(0, 10) || "";
  }

  function formatDate(value) {
    if (!value) return "訪問日未記録";
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("ja-JP", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(date);
  }

  function formatScore(value) {
    const score = Number(value);
    return Number.isInteger(score) ? String(score) : score.toFixed(1);
  }

  function scoreClass(score) {
    if (score >= 9) return "score-excellent";
    if (score >= 7) return "score-good";
    if (score >= 5) return "score-mid";
    return "score-low";
  }

  function textBlob(review) {
    return [
      review.facility,
      review.catchcopy,
      review.sauna,
      review.cold_bath,
      review.rest,
      review.flow,
      review.crowd,
      review.drawbacks,
      review.crowd_time,
      review.memo,
      ...(review.tags || []),
    ].join(" ").toLowerCase();
  }

  function filteredReviews() {
    const terms = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const filtered = state.reviews.filter((review) => {
      if (Number(review.score) < state.minScore) return false;
      if (state.tag !== "all" && !(review.tags || []).includes(state.tag)) return false;
      const haystack = textBlob(review);
      return terms.every((term) => haystack.includes(term));
    });

    return filtered.sort((a, b) => {
      if (state.sort === "score") {
        return Number(b.score) - Number(a.score) || activityDate(b).localeCompare(activityDate(a));
      }
      if (state.sort === "facility") {
        return a.facility.localeCompare(b.facility, "ja") || activityDate(b).localeCompare(activityDate(a));
      }
      return activityDate(b).localeCompare(activityDate(a)) || Number(b.score) - Number(a.score);
    });
  }

  function groupFacilities(reviews) {
    const groups = new Map();
    reviews.forEach((review) => {
      const current = groups.get(review.facility) || [];
      current.push(review);
      groups.set(review.facility, current);
    });

    return [...groups.entries()].map(([facility, items]) => {
      const sorted = [...items].sort((a, b) => activityDate(b).localeCompare(activityDate(a)));
      const average = items.reduce((sum, item) => sum + Number(item.score), 0) / items.length;
      return {
        facility,
        items: sorted,
        average,
        latest: sorted[0],
        tags: [...new Set(items.flatMap((item) => item.tags || []))],
      };
    }).sort((a, b) => b.average - a.average || b.items.length - a.items.length || a.facility.localeCompare(b.facility, "ja"));
  }

  function renderMetrics() {
    const reviews = state.reviews;
    const facilities = new Set(reviews.map((review) => review.facility));
    const average = reviews.length
      ? reviews.reduce((sum, review) => sum + Number(review.score), 0) / reviews.length
      : 0;
    const repeatFacilities = groupFacilities(reviews).filter((group) => group.items.length >= 2).length;

    $("#metricReviews").textContent = reviews.length;
    $("#metricFacilities").textContent = facilities.size;
    $("#metricAverage").textContent = average.toFixed(2);
    $("#metricRepeat").textContent = repeatFacilities;
  }

  function renderTagFilter() {
    const select = $("#tagFilter");
    const tags = [...new Set(state.reviews.flatMap((review) => review.tags || []))].sort((a, b) => a.localeCompare(b, "ja"));
    select.innerHTML = [
      '<option value="all">すべての特徴</option>',
      ...tags.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`),
    ].join("");
  }

  function renderRanking() {
    const groups = groupFacilities(state.reviews).slice(0, 10);
    const max = groups[0]?.average || 10;
    $("#rankingList").innerHTML = groups.map((group, index) => `
      <li class="sauna-ranking-row">
        <span class="rank-number">${index + 1}</span>
        <div class="rank-main">
          <div class="rank-title">
            <strong>${escapeHtml(group.facility)}</strong>
            <span>${formatScore(group.average)} / 10</span>
          </div>
          <div class="rank-bar"><span style="width:${Math.max(4, (group.average / max) * 100)}%"></span></div>
          <small>${group.items.length}回訪問 · 最新 ${formatScore(group.latest.score)}点</small>
        </div>
      </li>
    `).join("");
  }

  function detailRow(label, value) {
    if (!value) return "";
    return `<div class="review-detail"><dt>${label}</dt><dd>${escapeHtml(value).replace(/\n/g, "<br>")}</dd></div>`;
  }

  function renderFacilityCards() {
    const groups = groupFacilities(filteredReviews());
    const container = $("#facilityGrid");
    $("#resultCount").textContent = `${groups.length}施設・${groups.reduce((sum, group) => sum + group.items.length, 0)}件`;

    if (!groups.length) {
      container.innerHTML = '<p class="sauna-empty">条件に合うレビューがありません。サウナまで検索に耐えろと言われても困ります。</p>';
      return;
    }

    container.innerHTML = groups.map((group) => {
      const latest = group.latest;
      const details = [
        detailRow("サウナ", latest.sauna),
        detailRow("水風呂", latest.cold_bath),
        detailRow("休憩", latest.rest),
        detailRow("導線", latest.flow),
        detailRow("混雑", latest.crowd || latest.crowd_time),
        detailRow("弱点", latest.drawbacks),
        detailRow("次回メモ", latest.memo),
      ].join("");

      return `
        <article class="sauna-facility-card">
          <div class="facility-head">
            <div>
              <p class="facility-date">${formatDate(activityDate(latest))}</p>
              <h3>${escapeHtml(group.facility)}</h3>
            </div>
            <div class="facility-score ${scoreClass(group.average)}">
              <strong>${formatScore(group.average)}</strong><span>/10</span>
            </div>
          </div>
          <p class="facility-catchcopy">${escapeHtml(latest.catchcopy || "キャッチコピー未記録")}</p>
          <div class="facility-meta">
            <span>${group.items.length}回訪問</span>
            <span>最新 ${formatScore(latest.score)}点</span>
            ${latest.detail_level === "score_only" ? '<span class="legacy-badge">旧記録・点数のみ</span>' : ""}
          </div>
          <div class="tag-list">${group.tags.map((tag) => `<button type="button" class="tag-button" data-tag="${escapeHtml(tag)}">#${escapeHtml(tag)}</button>`).join("")}</div>
          ${details ? `<dl class="review-details">${details}</dl>` : '<p class="review-placeholder">詳細コメントは今後の再訪で育てる記録。</p>'}
          ${group.items.length > 1 ? `
            <details class="visit-history">
              <summary>訪問履歴を見る</summary>
              <ol>${group.items.map((item) => `
                <li><span>${formatDate(activityDate(item))}</span><strong>${formatScore(item.score)}点</strong><small>${escapeHtml(item.catchcopy || "コメント未記録")}</small></li>
              `).join("")}</ol>
            </details>
          ` : ""}
        </article>
      `;
    }).join("");

    container.querySelectorAll("[data-tag]").forEach((button) => {
      button.addEventListener("click", () => {
        state.tag = button.dataset.tag;
        $("#tagFilter").value = state.tag;
        renderFacilityCards();
      });
    });
  }

  function renderRecent() {
    const reviews = [...state.reviews]
      .sort((a, b) => activityDate(b).localeCompare(activityDate(a)))
      .slice(0, 8);
    $("#recentList").innerHTML = reviews.map((review) => `
      <li>
        <span>${formatDate(activityDate(review))}</span>
        <strong>${escapeHtml(review.facility)}</strong>
        <b class="${scoreClass(Number(review.score))}">${formatScore(review.score)}点</b>
        <small>${escapeHtml(review.catchcopy || "コメント未記録")}</small>
      </li>
    `).join("");
  }

  function bindControls() {
    $("#reviewSearch").addEventListener("input", (event) => {
      state.query = event.target.value;
      renderFacilityCards();
    });
    $("#scoreFilter").addEventListener("change", (event) => {
      state.minScore = Number(event.target.value);
      renderFacilityCards();
    });
    $("#tagFilter").addEventListener("change", (event) => {
      state.tag = event.target.value;
      renderFacilityCards();
    });
    $("#sortOrder").addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderFacilityCards();
    });
    $("#resetFilters").addEventListener("click", () => {
      state.query = "";
      state.minScore = 0;
      state.tag = "all";
      state.sort = "latest";
      $("#reviewSearch").value = "";
      $("#scoreFilter").value = "0";
      $("#tagFilter").value = "all";
      $("#sortOrder").value = "latest";
      renderFacilityCards();
    });
  }

  async function init() {
    try {
      const [reviewsResponse, summaryResponse] = await Promise.all([
        fetch("data/sauna/reviews.json", { cache: "no-store" }),
        fetch("data/sauna/summary.json", { cache: "no-store" }),
      ]);
      if (!reviewsResponse.ok) throw new Error(`reviews.json: ${reviewsResponse.status}`);
      const dataset = await reviewsResponse.json();
      state.reviews = Array.isArray(dataset.reviews) ? dataset.reviews : [];
      state.summary = summaryResponse.ok ? await summaryResponse.json() : null;

      renderMetrics();
      renderTagFilter();
      renderRanking();
      renderFacilityCards();
      renderRecent();
      bindControls();
      $("#dataStatus").textContent = `最終更新: ${formatDate((dataset.updated_at || "").slice(0, 10))}`;
    } catch (error) {
      console.error(error);
      $("#facilityGrid").innerHTML = `
        <p class="sauna-empty">
          レビューデータを読み込めませんでした。GitHub Pagesまたはローカルサーバー経由で開いてください。
        </p>`;
      $("#dataStatus").textContent = "データ読み込み失敗";
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
