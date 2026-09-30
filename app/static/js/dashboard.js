/**
 * FlowForge — дашборд пользователя.
 * Загружает список проектов текущего пользователя. Создание нового —
 * одно действие по клику, без формы: "Название"/"Описание" при
 * создании не запрашиваются (project.default_name на backend), человек
 * переименует проект прямо на титульном листе, когда до этого дойдёт.
 */
(function () {
  "use strict";

  const grid = document.getElementById("projects-grid");
  const emptyState = document.getElementById("empty-state");
  const btnNew = document.getElementById("btn-new-project");

  function projectUrl(project) {
    return project.slug ? "/" + project.slug : "/p/" + project.id;
  }

  function roleBadgeClass(role) {
    return "badge-role-" + (role || "viewer");
  }

  function visibilityBadgeClass(visibility) {
    if (visibility === "public") return "badge-success";
    if (visibility === "link") return "badge-warning";
    return "badge-neutral";
  }

  function formatUpdatedAt(isoString) {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function renderProjects(projects) {
    grid.innerHTML = "";
    emptyState.style.display = projects.length === 0 ? "block" : "none";

    projects.forEach((project) => {
      const card = document.createElement("a");
      card.href = projectUrl(project);
      card.className = "card";
      card.style.display = "block";

      const title = document.createElement("p");
      title.className = "project-card-title";
      title.textContent = project.name;

      const updated = document.createElement("p");
      updated.className = "project-card-desc";
      updated.textContent = formatUpdatedAt(project.updated_at);

      const meta = document.createElement("div");
      meta.className = "project-card-meta";

      const visBadge = document.createElement("span");
      visBadge.className = "badge " + visibilityBadgeClass(project.visibility);
      visBadge.textContent = FF.t("ui.visibility." + project.visibility);

      const roleBadge = document.createElement("span");
      roleBadge.className = "badge " + roleBadgeClass(project.role);
      roleBadge.textContent = FF.t("ui.settings.role_" + (project.role || "viewer"));

      meta.appendChild(visBadge);
      meta.appendChild(roleBadge);

      card.appendChild(title);
      card.appendChild(updated);
      card.appendChild(meta);
      grid.appendChild(card);
    });
  }

  async function loadProjects() {
    try {
      const projects = await FF.api.get("/api/projects");
      renderProjects(projects);
    } catch (err) {
      console.error("Failed to load projects:", err);
    }
  }

  async function createProject() {
    btnNew.disabled = true;
    try {
      const project = await FF.api.post("/api/projects", {});
      window.location.href = projectUrl(project);
    } catch (err) {
      alert(err.message);
      btnNew.disabled = false;
    }
  }

  btnNew.addEventListener("click", createProject);
  loadProjects();
})();
