// The side panel's behaviour (design principle 2; F2 design, Step 1). Plain JavaScript, no build.
// - Opens as a modal dialog, from the address on a full load or when htmx swaps it in, and moves
//   focus to the selected tab.
// - Tabs follow the WAI-ARIA tabs pattern: arrow keys, Home and End move between them and show
//   the tab; the address follows (hx-replace-url), so a copied link reopens the same tab.
// - Escape or the close button closes it, puts the panel-free address in the history, and returns
//   focus to the figure that opened it. Back reopens it (htmx reloads the address, which holds
//   the panel's state).
// - After htmx settles a tab's content, a polite live region says which tab is showing.
(function () {
  "use strict";

  var opener = null; // the figure that opened the panel, for focus on close

  function panel() {
    return document.querySelector("dialog[data-panel]");
  }

  function tabs(dialog) {
    return Array.prototype.slice.call(dialog.querySelectorAll('[role="tab"]'));
  }

  function selectedTab(dialog) {
    return dialog.querySelector('[role="tab"][aria-selected="true"]') || tabs(dialog)[0];
  }

  function open(dialog) {
    if (dialog.open && !dialog.matches(":modal")) {
      dialog.close(); // rendered open for a page without JavaScript; reopen it as a modal
    }
    if (!dialog.open) {
      dialog.showModal();
    }
    var tab = selectedTab(dialog);
    if (tab) {
      tab.focus();
    }
  }

  function close(dialog) {
    var url = dialog.getAttribute("data-close-url");
    var figura = dialog.getAttribute("data-figura");
    dialog.close();
    dialog.remove();
    if (url) {
      history.pushState({ htmx: true }, "", url);
    }
    var target = opener && document.contains(opener) ? opener : null;
    if (!target && figura) {
      target = document.querySelector('[data-figura="' + figura + '"]:not(dialog)');
    }
    if (target) {
      target.focus();
    }
    opener = null;
  }

  function mark(dialog, tab) {
    tabs(dialog).forEach(function (other) {
      var on = other === tab;
      other.setAttribute("aria-selected", on ? "true" : "false");
      other.setAttribute("tabindex", on ? "0" : "-1");
    });
    var body = dialog.querySelector('[role="tabpanel"]');
    if (body) {
      body.setAttribute("aria-labelledby", tab.id);
    }
  }

  function select(dialog, tab) {
    mark(dialog, tab);
    tab.focus();
    tab.click(); // htmx fetches the tab's content and updates the address
  }

  function announce(dialog) {
    var live = dialog.querySelector("[data-panel-live]");
    var tab = selectedTab(dialog);
    var template = dialog.getAttribute("data-announce") || "{tab}";
    if (live && tab) {
      live.textContent = template.replace("{tab}", tab.textContent.trim());
    }
  }

  document.addEventListener("keydown", function (event) {
    var tab = event.target.closest && event.target.closest('[role="tab"]');
    var dialog = tab && tab.closest("dialog[data-panel]");
    if (!dialog) {
      return;
    }
    var all = tabs(dialog);
    var index = all.indexOf(tab);
    var next = null;
    if (event.key === "ArrowRight") next = all[(index + 1) % all.length];
    else if (event.key === "ArrowLeft") next = all[(index - 1 + all.length) % all.length];
    else if (event.key === "Home") next = all[0];
    else if (event.key === "End") next = all[all.length - 1];
    if (next) {
      event.preventDefault();
      select(dialog, next);
    }
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-panel-close]");
    if (button) {
      close(button.closest("dialog[data-panel]"));
      return;
    }
    var tab = event.target.closest && event.target.closest('[role="tab"]');
    var dialog = tab && tab.closest("dialog[data-panel]");
    if (dialog) {
      mark(dialog, tab); // htmx already handles the click itself; only the state follows here
    }
  });

  // Escape fires "cancel" on a modal dialog: close it our way, so the address and focus follow.
  document.addEventListener(
    "cancel",
    function (event) {
      if (event.target.matches && event.target.matches("dialog[data-panel]")) {
        event.preventDefault();
        close(event.target);
      }
    },
    true
  );

  document.addEventListener("htmx:beforeRequest", function (event) {
    var elt = event.detail.elt;
    if (elt && elt.hasAttribute("data-figura") && !elt.closest("dialog")) {
      opener = elt;
    }
  });

  // afterSettle, not afterSwap: htmx binds the new tabs' handlers while settling, so a key
  // pressed the moment the panel opens fetches the tab instead of following its link
  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.detail.target;
    if (target.id === "panel-host") {
      var dialog = panel();
      if (dialog) open(dialog);
    } else if (target.id === "panel-contenido") {
      announce(target.closest("dialog[data-panel]"));
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var dialog = panel();
    if (dialog && dialog.hasAttribute("data-open")) {
      open(dialog);
    }
  });
})();
