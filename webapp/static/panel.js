// The side panel's behaviour (design principle 2; F2 design, Step 1). Plain JavaScript, no build.
// - Opens as a modal dialog, from the address on a full load or when htmx swaps it in, and moves
//   focus to the selected tab.
// - Tabs follow the WAI-ARIA tabs pattern: arrow keys, Home and End move between them and show
//   the tab; the address follows (hx-replace-url), so a copied link reopens the same tab.
// - Escape, the close link or a click on the dimmed page closes it, puts the panel-free address in the history, and returns
//   focus to the figure that opened it. Back reopens it (htmx reloads the address, which holds
//   the panel's state).
// - After htmx settles a tab's content, a polite live region says which tab is showing; a tab
//   that fails to load shows the catalogue's error message in the panel, with a retry link.
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

  function say(dialog, text) {
    var live = dialog.querySelector("[data-panel-live]");
    if (live) live.textContent = text;
  }

  // Announce the tab whose content actually loaded, and make sure it is the one marked selected
  // (requests are serialised by hx-sync, so this is the newest one; this is the backstop).
  function settled(dialog) {
    var body = dialog.querySelector("[data-pestana]");
    var tab = body && dialog.querySelector("#pestana-" + body.getAttribute("data-pestana"));
    if (!tab) return;
    if (tab.getAttribute("aria-selected") !== "true") mark(dialog, tab);
    var template = dialog.getAttribute("data-announce") || "{tab}";
    say(dialog, template.replace("{tab}", tab.textContent.trim()));
  }

  // A tab that fails to load says so inside the panel, in the student's language; its link
  // (the address with that tab) is the retry. Never the previous tab's content under a new name.
  function tabFailed(dialog, tab) {
    var message = dialog.getAttribute("data-tab-error") || "";
    var body = dialog.querySelector('[role="tabpanel"]');
    var p = document.createElement("p");
    p.className = "tab-error";
    p.setAttribute("data-tab-failed", tab.id.replace("pestana-", ""));
    var retry = document.createElement("a");
    retry.href = tab.getAttribute("href");
    retry.textContent = message;
    p.appendChild(retry);
    body.replaceChildren(p);
    say(dialog, message);
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
    else if (event.key === " " || event.key === "Enter") next = tab; // links ignore Space
    if (next) {
      event.preventDefault();
      select(dialog, next);
    }
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-panel-close]");
    if (button) {
      event.preventDefault(); // the link closes without JavaScript; here, in place
      close(button.closest("dialog[data-panel]"));
      return;
    }
    // a click on the dimmed page lands on the dialog itself (its ::backdrop): close
    if (event.target.matches && event.target.matches("dialog[data-panel]")) {
      var r = event.target.getBoundingClientRect();
      var inside =
        event.clientX >= r.left &&
        event.clientX <= r.right &&
        event.clientY >= r.top &&
        event.clientY <= r.bottom;
      if (!inside) {
        close(event.target);
        return;
      }
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
      settled(target.closest("dialog[data-panel]"));
    }
  });

  function failed(event) {
    var elt = event.detail.elt;
    var dialog = elt && elt.closest && elt.closest("dialog[data-panel]");
    if (dialog && elt.getAttribute("role") === "tab") {
      tabFailed(dialog, elt);
    } else if (elt && elt.hasAttribute("data-figura") && elt.href) {
      window.location.href = elt.href; // the panel failed to open: the full page shows why
    }
  }
  document.addEventListener("htmx:responseError", failed);
  document.addEventListener("htmx:sendError", failed);

  document.addEventListener("DOMContentLoaded", function () {
    var dialog = panel();
    if (dialog && dialog.hasAttribute("data-open")) {
      open(dialog);
    }
  });
})();
