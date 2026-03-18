/* ======================================================================
   Email Campaign Manager -- Core JavaScript Utilities
   ====================================================================== */

/**
 * Fetch wrapper with error handling.
 * Returns parsed JSON on success, throws on error.
 */
function fetchAPI(url, options) {
    options = options || {};
    return fetch(url, options).then(function(resp) {
        if (!resp.ok) {
            return resp.json().then(function(data) {
                var err = new Error(data.error || 'Request failed');
                err.status = resp.status;
                throw err;
            }).catch(function(parseErr) {
                if (parseErr.status) throw parseErr;
                var err = new Error('Request failed with status ' + resp.status);
                err.status = resp.status;
                throw err;
            });
        }
        return resp.json();
    });
}


/**
 * Show a toast notification.
 * @param {string} message
 * @param {string} type - 'success', 'error', 'info', 'warning'
 */
function showNotification(message, type) {
    type = type || 'info';
    var container = document.getElementById('notificationContainer');
    if (!container) return;

    var el = document.createElement('div');
    el.className = 'notification ' + type;
    el.textContent = message;
    container.appendChild(el);

    // Auto-dismiss after 4 seconds
    setTimeout(function() {
        el.classList.add('fadeout');
        setTimeout(function() {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 300);
    }, 4000);
}


/**
 * Format an ISO date string to a readable format.
 * @param {string} isoString
 * @param {boolean} includeTime - include time portion
 * @returns {string}
 */
function formatDate(isoString, includeTime) {
    if (!isoString) return '--';
    var d = new Date(isoString);
    if (isNaN(d.getTime())) return '--';

    var options = { year: 'numeric', month: 'short', day: 'numeric' };
    if (includeTime) {
        options.hour = '2-digit';
        options.minute = '2-digit';
    }
    return d.toLocaleDateString('en-US', options);
}


/**
 * Format a date as relative time string.
 * @param {string} isoString
 * @returns {string}
 */
function formatRelativeTime(isoString) {
    if (!isoString) return '';
    var d = new Date(isoString);
    if (isNaN(d.getTime())) return '';

    var now = new Date();
    var diff = now - d;
    var seconds = Math.floor(diff / 1000);
    var minutes = Math.floor(seconds / 60);
    var hours = Math.floor(minutes / 60);
    var days = Math.floor(hours / 24);

    if (seconds < 60) return 'just now';
    if (minutes < 60) return minutes + (minutes === 1 ? ' minute ago' : ' minutes ago');
    if (hours < 24) return hours + (hours === 1 ? ' hour ago' : ' hours ago');
    if (days < 7) return days + (days === 1 ? ' day ago' : ' days ago');
    return formatDate(isoString);
}


/**
 * Escape HTML to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}


/**
 * Get a badge HTML string for a status value.
 * @param {string} status
 * @returns {string}
 */
function statusBadge(status) {
    if (!status) return '<span class="badge badge-draft">unknown</span>';
    return '<span class="badge badge-' + escapeHtml(status) + '">' + escapeHtml(status) + '</span>';
}


/**
 * Debounce function.
 * @param {Function} fn
 * @param {number} delay
 * @returns {Function}
 */
function debounce(fn, delay) {
    var timer;
    return function() {
        var context = this;
        var args = arguments;
        clearTimeout(timer);
        timer = setTimeout(function() {
            fn.apply(context, args);
        }, delay);
    };
}


/**
 * Animate a counter from 0 to a target value.
 * @param {HTMLElement} el
 * @param {number} target
 * @param {string} suffix - optional suffix like '%'
 * @param {number} duration - milliseconds
 */
function animateCounter(el, target, suffix, duration) {
    suffix = suffix || '';
    duration = duration || 800;
    var start = 0;
    var startTime = null;

    function step(timestamp) {
        if (!startTime) startTime = timestamp;
        var progress = Math.min((timestamp - startTime) / duration, 1);
        var current = Math.floor(progress * target);
        el.textContent = current + suffix;
        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            el.textContent = target + suffix;
        }
    }

    requestAnimationFrame(step);
}


/**
 * Notes autosave setup.
 * @param {string} textareaId
 * @param {number} contactId
 */
function setupNotesAutosave(textareaId, contactId) {
    var textarea = document.getElementById(textareaId);
    var statusEl = document.getElementById('notesSaveStatus');
    if (!textarea) return;

    var save = debounce(function() {
        if (statusEl) statusEl.textContent = 'Saving...';
        fetchAPI('/api/contacts/' + contactId + '/notes', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes: textarea.value })
        }).then(function() {
            if (statusEl) statusEl.textContent = 'Saved';
            setTimeout(function() {
                if (statusEl) statusEl.textContent = '';
            }, 2000);
        }).catch(function() {
            if (statusEl) statusEl.textContent = 'Save failed';
        });
    }, 1000);

    textarea.addEventListener('input', save);
}
