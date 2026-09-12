(function () {
  const root = document.documentElement;
  const storedTheme = localStorage.getItem('mecard-admin-theme');
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const applyTheme = (dark) => {
    root.classList.toggle('dark', dark);
    document.body.classList.toggle('dark-mode', dark);
    document.querySelectorAll('[data-theme-icon]').forEach((icon) => { icon.textContent = dark ? '☀' : '☾'; });
  };
  applyTheme(storedTheme ? storedTheme === 'dark' : prefersDark);
  document.querySelectorAll('[data-theme-toggle]').forEach((button) => button.addEventListener('click', () => {
    const dark = !root.classList.contains('dark');
    localStorage.setItem('mecard-admin-theme', dark ? 'dark' : 'light');
    applyTheme(dark);
  }));

  // Django's own sidebar button changes its internal state, while the custom
  // shell also needs to release the content width when the sidebar collapses.
  const sidebarToggle = document.querySelector('.toggle-nav-sidebar');
  const sidebar = document.querySelector('#nav-sidebar');
  const setSidebarState = (collapsed) => {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    if (sidebar) sidebar.classList.toggle('custom-collapsed', collapsed);
    localStorage.setItem('mecard-admin-sidebar', collapsed ? 'collapsed' : 'open');
  };
  if (sidebarToggle && sidebar) {
    setSidebarState(localStorage.getItem('mecard-admin-sidebar') === 'collapsed');
    // Capture and stop Django's built-in handler; otherwise both handlers
    // toggle the sidebar and it flashes open before closing again.
    document.addEventListener('click', (event) => {
      const button = event.target.closest('.toggle-nav-sidebar');
      if (!button) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setSidebarState(!document.body.classList.contains('sidebar-collapsed'));
    }, true);
  }
})();
