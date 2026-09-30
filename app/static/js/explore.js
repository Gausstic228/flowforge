/**
 * FlowForge — публичный каталог. Показывает все проекты с
 * visibility=public, доступен без авторизации (см.
 * app/routes/projects.py -> list_public_projects).
 */
(function () {
  "use strict";

  const grid = document.getElementById("projects-grid");
  const emptyState = document.getElementById("empty-state");

  function projectUrl(project) {
    return project.slug ? "/" + project.slug : "/p/" + project.id;
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

      const desc = document.createElement("p");
      desc.className = "project-card-desc";
      desc.textContent = project.description || "";

      const meta = document.createElement("div");
      meta.className = "project-card-meta";

      const owner = document.createElement("span");
      owner.className = "text-secondary text-sm";
      owner.textContent = "@" + (project.owner.username || project.owner.display_name);

      meta.appendChild(owner);
      card.appendChild(title);
      card.appendChild(desc);
      card.appendChild(meta);
      grid.appendChild(card);
    });
  }

  async function loadProjects() {
    try {
      const projects = await FF.api.get("/api/projects/public");
      renderProjects(projects);
    } catch (err) {
      console.error("Failed to load public projects:", err);
    }
  }

  loadProjects();
})();
