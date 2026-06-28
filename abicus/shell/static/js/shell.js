(() => {
  // ⌘K / Ctrl-K focuses the search box. v1: focus only, no command palette.
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      const input = document.querySelector(".search-input");
      if (input) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    }
  });
})();
