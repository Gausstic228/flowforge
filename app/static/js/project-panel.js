/**
 * FlowForge — project-panel.js
 *
 * Панели вокруг рабочей области, не зависящие от того, какой узел сейчас
 * открыт: модалка настроек проекта (видимость/slug/команда/ссылки) и
 * панель/модалка предложений. В отличие от более ранней версии, "текущий
 * узел" здесь не зафиксирован при инициализации — editor.js вызывает
 * setCurrentNode(nodeId) при каждом переключении в дереве, а модуль сам
 * берёт актуальное значение в момент действия (открыть список предложений,
 * отправить новое), а не то, что было при первом init().
 */
window.FF = window.FF || {};

window.FF.panel = (function () {
  "use strict";

  let project = null;   // состояние проекта — обновляется после каждого изменения
  let currentNodeId = null;
  let pendingPatch = null; // патч из canvas.js, ждущий отправки как Suggestion

  function setProject(p) { project = p; }
  function setCurrentNode(nodeId) { currentNodeId = nodeId; }
  function getProject() { return project; }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ------------------------------------------------------------------
  // Модалка настроек проекта
  // ------------------------------------------------------------------
  function openSettings() {
    document.getElementById("settings-modal").style.display = "flex";
    document.getElementById("visibility-select").value = project.visibility;
    _renderSlugDisplay();
    _renderMembers();
    _renderSettingsLinks();
  }

  function closeSettings() {
    document.getElementById("settings-modal").style.display = "none";
  }

  function _renderSlugDisplay() {
    const host = document.getElementById("slug-display");
    host.textContent = project.slug ? window.location.origin + "/" + project.slug : "";
  }

  function _renderMembers() {
    const host = document.getElementById("members-list");
    host.innerHTML = "";

    const ownerRow = document.createElement("div");
    ownerRow.className = "member-row";
    ownerRow.innerHTML = `<span>@${escapeHtml(project.owner.username || project.owner.display_name)}</span>
      <span class="badge badge-role-owner">${FF.t("ui.settings.role_owner")}</span>`;
    host.appendChild(ownerRow);

    (project.members || []).forEach((member) => {
      const row = document.createElement("div");
      row.className = "member-row";
      row.innerHTML = `<span>@${escapeHtml(member.username || member.display_name)}</span>`;
      const right = document.createElement("div");
      right.className = "flex gap-2 items-center";
      const badge = document.createElement("span");
      badge.className = "badge badge-role-" + member.role;
      badge.textContent = FF.t("ui.settings.role_" + member.role);
      const removeBtn = document.createElement("button");
      removeBtn.className = "btn btn-ghost btn-sm";
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", () => _removeMember(member.id));
      right.appendChild(badge);
      right.appendChild(removeBtn);
      row.appendChild(right);
      host.appendChild(row);
    });
  }

  function _renderSettingsLinks() {
    const host = document.getElementById("settings-links-list");
    host.innerHTML = "";
    (project.links || []).forEach((link) => {
      const row = document.createElement("div");
      row.className = "link-row";
      row.innerHTML = `<span>${escapeHtml(link.title)}</span>`;
      const removeBtn = document.createElement("button");
      removeBtn.className = "btn btn-ghost btn-sm";
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", () => _removeLink(link.id));
      row.appendChild(removeBtn);
      host.appendChild(row);
    });
  }

  async function _changeVisibility(newVisibility) {
    try {
      project = await FF.api.patch(`/api/projects/${project.id}/visibility`, { visibility: newVisibility });
      _renderSlugDisplay();
    } catch (err) {
      alert(err.message);
    }
  }

  async function _addMember(username, role) {
    if (!username.trim()) return;
    try {
      project = await FF.api.post(`/api/projects/${project.id}/members`, { username, role });
      _renderMembers();
    } catch (err) {
      alert(err.message);
    }
  }

  async function _removeMember(userId) {
    try {
      project = await FF.api.del(`/api/projects/${project.id}/members/${userId}`);
      _renderMembers();
    } catch (err) {
      alert(err.message);
    }
  }

  async function _addLink(title, url) {
    if (!title.trim() || !url.trim()) return;
    try {
      project = await FF.api.post(`/api/projects/${project.id}/links`, { title, url });
      _renderSettingsLinks();
    } catch (err) {
      alert(err.message);
    }
  }

  async function _removeLink(linkId) {
    try {
      project = await FF.api.del(`/api/projects/${project.id}/links/${linkId}`);
      _renderSettingsLinks();
    } catch (err) {
      alert(err.message);
    }
  }

  function _wireSettingsModal() {
    document.getElementById("btn-open-settings").addEventListener("click", openSettings);
    document.getElementById("btn-close-settings").addEventListener("click", closeSettings);
    document.getElementById("settings-modal").addEventListener("click", (e) => {
      if (e.target.id === "settings-modal") closeSettings();
    });
    document.getElementById("visibility-select").addEventListener("change", (e) => _changeVisibility(e.target.value));

    document.getElementById("btn-add-member").addEventListener("click", () => {
      const input = document.getElementById("new-member-username");
      const roleSelect = document.getElementById("new-member-role");
      _addMember(input.value, roleSelect.value).then(() => { input.value = ""; });
    });

    document.getElementById("btn-add-link").addEventListener("click", () => {
      const titleInput = document.getElementById("new-link-title");
      const urlInput = document.getElementById("new-link-url");
      _addLink(titleInput.value, urlInput.value).then(() => {
        titleInput.value = "";
        urlInput.value = "";
      });
    });
  }

  // ------------------------------------------------------------------
  // Предложения (Suggestions) — привязаны к currentNodeId в МОМЕНТ
  // действия, а не к тому, что было при init(): узел меняется при
  // переключении по дереву без перезагрузки страницы.
  // ------------------------------------------------------------------
  function openSuggestionsPanel() {
    document.getElementById("suggestions-panel").style.display = "block";
    _loadSuggestions();
  }

  function closeSuggestionsPanel() {
    document.getElementById("suggestions-panel").style.display = "none";
  }

  /**
   * patch — необязателен: пустой список означает "идея без конкретной
   * правки", просто текст для разработчиков (см. Suggestion.patch=null
   * на backend). nodeId явно не передаётся — берём currentNodeId, чтобы
   * предложение всегда уходило к тому узлу, что открыт сейчас.
   */
  function openSuggestionModal(patch) {
    pendingPatch = patch || null;
    document.getElementById("suggestion-modal").style.display = "flex";
    document.getElementById("suggestion-title").value = "";
    document.getElementById("suggestion-comment").value = "";
  }

  function closeSuggestionModal() {
    document.getElementById("suggestion-modal").style.display = "none";
    pendingPatch = null;
  }

  async function _submitSuggestion() {
    const title = document.getElementById("suggestion-title").value;
    const comment = document.getElementById("suggestion-comment").value;
    try {
      await FF.api.post(`/api/suggestions/node/${currentNodeId}`, { title, comment, patch: pendingPatch });
      closeSuggestionModal();
      if (document.getElementById("suggestions-panel").style.display !== "none") _loadSuggestions();
    } catch (err) {
      alert(err.message);
    }
  }

  function _statusBadgeClass(status) {
    if (status === "accepted") return "badge-success";
    if (status === "rejected") return "badge-danger";
    return "badge-warning";
  }

  async function _loadSuggestions() {
    const host = document.getElementById("suggestions-list");
    host.innerHTML = "";
    try {
      const suggestions = await FF.api.get(`/api/suggestions/node/${currentNodeId}?status=pending`);
      if (suggestions.length === 0) {
        const empty = document.createElement("p");
        empty.className = "text-secondary text-sm";
        empty.textContent = FF.t("ui.canvas.suggestions_empty");
        host.appendChild(empty);
        return;
      }
      suggestions.forEach((s) => host.appendChild(_renderSuggestionItem(s)));
    } catch (err) {
      console.error("Failed to load suggestions:", err);
    }
  }

  function _renderSuggestionItem(suggestion) {
    const item = document.createElement("div");
    item.className = "validation-item";
    item.style.flexDirection = "column";
    item.style.alignItems = "stretch";
    item.style.cursor = "default";

    const header = document.createElement("div");
    header.className = "flex items-center justify-between";
    header.innerHTML = `<strong>${escapeHtml(suggestion.title)}</strong>
      <span class="badge ${_statusBadgeClass(suggestion.status)}">${suggestion.status}</span>`;
    item.appendChild(header);

    const author = document.createElement("p");
    author.className = "text-faint text-sm";
    author.style.margin = "4px 0";
    author.textContent = "@" + (suggestion.author.username || suggestion.author.display_name);
    item.appendChild(author);

    if (suggestion.comment) {
      const comment = document.createElement("p");
      comment.className = "text-sm";
      comment.style.margin = "0 0 8px";
      comment.textContent = suggestion.comment;
      item.appendChild(comment);
    }

    if (project.can.edit) {
      const actions = document.createElement("div");
      actions.className = "flex gap-2";

      const acceptBtn = document.createElement("button");
      acceptBtn.className = "btn btn-primary btn-sm";
      acceptBtn.textContent = FF.t("ui.canvas.accept");
      acceptBtn.addEventListener("click", async () => {
        try {
          await FF.api.post(`/api/suggestions/${suggestion.id}/accept`);
          _loadSuggestions();
          if (window.FF.editor) window.FF.editor.reloadCurrentNode();
        } catch (err) {
          alert(err.message);
        }
      });

      const rejectBtn = document.createElement("button");
      rejectBtn.className = "btn btn-danger btn-sm";
      rejectBtn.textContent = FF.t("ui.canvas.reject");
      rejectBtn.addEventListener("click", async () => {
        try {
          await FF.api.post(`/api/suggestions/${suggestion.id}/reject`);
          _loadSuggestions();
        } catch (err) {
          alert(err.message);
        }
      });

      actions.appendChild(acceptBtn);
      actions.appendChild(rejectBtn);
      item.appendChild(actions);
    }

    return item;
  }

  function _wireSuggestionsUi() {
    document.getElementById("btn-suggestions").addEventListener("click", openSuggestionsPanel);
    document.getElementById("btn-close-suggestions").addEventListener("click", closeSuggestionsPanel);
    document.getElementById("btn-new-suggestion").addEventListener("click", () => openSuggestionModal(null));

    document.getElementById("btn-cancel-suggestion").addEventListener("click", closeSuggestionModal);
    document.getElementById("suggestion-modal").addEventListener("click", (e) => {
      if (e.target.id === "suggestion-modal") closeSuggestionModal();
    });
    document.getElementById("btn-submit-suggestion").addEventListener("click", _submitSuggestion);
  }

  // ------------------------------------------------------------------
  // Инициализация — вызывается один раз при загрузке editor.html
  // ------------------------------------------------------------------
  function init(initialProject) {
    setProject(initialProject);
    _wireSettingsModal();
    _wireSuggestionsUi();
  }

  return {
    init,
    setProject,
    setCurrentNode,
    getProject,
    openSuggestionModal,
  };
})();
