/**
 * KYC Service - Main frontend script
 * Toasts (bottom-right), sidebar, copy, Django messages
 */
(function () {
  'use strict';

  var TOAST_DURATION = 4500;

  function ensureToastContainer() {
    var id = 'toast-container';
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      el.className = 'toast-container';
      document.body.appendChild(el);
    }
    return el;
  }

  function getToastIcon(type) {
    switch (type) {
      case 'error': return 'fa-circle-xmark';
      case 'warning': return 'fa-triangle-exclamation';
      case 'info': return 'fa-circle-info';
      default: return 'fa-circle-check';
    }
  }

  function showToast(type, message) {
    if (typeof type === 'string' && typeof message === 'undefined') {
      message = type;
      type = 'success';
    }
    type = type || 'success';
    var container = ensureToastContainer();
    var toast = document.createElement('div');
    toast.className = 'toast-item ' + type;
    toast.setAttribute('role', 'alert');
    toast.innerHTML =
      '<span class="toast-icon"><i class="fas ' + getToastIcon(type) + '"></i></span>' +
      '<span class="toast-text">' + escapeHtml(String(message)) + '</span>' +
      '<button type="button" class="toast-close" aria-label="Close"><i class="fas fa-times"></i></button>';
    container.appendChild(toast);

    function remove() {
      toast.classList.add('toast-out');
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 300);
    }

    toast.querySelector('.toast-close').addEventListener('click', remove);
    var t = setTimeout(remove, TOAST_DURATION);
    toast._toastTimer = t;
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  window.showToast = showToast;

  // Django messages: read from hidden container and show as toasts
  document.addEventListener('DOMContentLoaded', function () {
    var wrap = document.getElementById('django-messages-toasts');
    if (wrap) {
      var items = wrap.querySelectorAll('[data-tag][data-message]');
      items.forEach(function (el) {
        var tag = (el.getAttribute('data-tag') || 'info').toLowerCase();
        if (tag === 'debug') return;
        var msg = el.getAttribute('data-message') || '';
        showToast(tag, msg);
      });
    }
  });

  // Copy to clipboard (show success toast)
  window.copyKey = window.copyToClipboard = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showToast('success', 'Copied to clipboard');
      }).catch(function () {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  };

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      showToast('success', 'Copied to clipboard');
    } catch (err) {
      showToast('error', 'Copy failed');
    }
    document.body.removeChild(ta);
  }

  // Sidebar toggle (mobile)
  var sidebar = document.getElementById('app-sidebar');
  var sidebarToggle = document.getElementById('sidebar-toggle');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', function () {
      sidebar.classList.toggle('show');
    });
    document.addEventListener('click', function (e) {
      if (window.innerWidth <= 991 && sidebar.classList.contains('show') &&
          !sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
        sidebar.classList.remove('show');
      }
    });
  }

  // Table search
  var searchInput = document.getElementById('searchInput');
  var usersTable = document.getElementById('usersTable');
  if (searchInput && usersTable) {
    searchInput.addEventListener('keyup', function () {
      var q = this.value.toLowerCase();
      var rows = usersTable.querySelectorAll('tbody tr');
      rows.forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
      });
    });
  }

  document.querySelectorAll('.dropdown-toggle').forEach(function (el) {
    el.addEventListener('click', function () {
      var expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', !expanded);
    });
  });

  // Header scroll state (app-header and landing)
  var appHeader = document.getElementById('appHeader') || document.getElementById('mainHeader');
  if (appHeader) {
    function onScroll() {
      appHeader.classList.toggle('scrolled', window.scrollY > 16);
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
})();
