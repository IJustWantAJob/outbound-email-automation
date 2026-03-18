/* ======================================================================
   Email Campaign Manager -- Contact Management JavaScript
   ====================================================================== */


/* ============================== Contact List ============================== */

var ContactsManager = {
    currentPage: 1,
    perPage: 50,
    filters: {},

    init: function() {
        this.bindFilters();
        this.loadContacts();
    },

    bindFilters: function() {
        var self = this;
        var statusEl = document.getElementById('filterStatus');
        var waveEl = document.getElementById('filterWave');
        var searchEl = document.getElementById('filterSearch');

        if (statusEl) statusEl.addEventListener('change', function() {
            self.filters.status = this.value;
            self.currentPage = 1;
            self.loadContacts();
        });

        if (waveEl) waveEl.addEventListener('change', function() {
            self.filters.wave = this.value;
            self.currentPage = 1;
            self.loadContacts();
        });

        if (searchEl) searchEl.addEventListener('input', debounce(function() {
            self.filters.search = searchEl.value;
            self.currentPage = 1;
            self.loadContacts();
        }, 300));
    },

    loadContacts: function() {
        var params = new URLSearchParams();
        params.set('page', this.currentPage);
        params.set('per_page', this.perPage);
        if (this.filters.status) params.set('status', this.filters.status);
        if (this.filters.wave) params.set('wave', this.filters.wave);
        if (this.filters.search) params.set('search', this.filters.search);

        var self = this;
        fetchAPI('/api/contacts?' + params.toString()).then(function(data) {
            self.renderTable(data.contacts, data.total, data.page, data.per_page);
        }).catch(function(err) {
            var tbody = document.getElementById('contactsTableBody');
            if (tbody) tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><h3>Failed to load contacts</h3></div></td></tr>';
        });
    },

    renderTable: function(contacts, total, page, perPage) {
        var tbody = document.getElementById('contactsTableBody');
        if (!tbody) return;

        if (!contacts || contacts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><h3>No contacts found</h3><p>Add contacts manually or import from a markdown file.</p></div></td></tr>';
            document.getElementById('contactsPagination').innerHTML = '';
            return;
        }

        var startIdx = (page - 1) * perPage;
        tbody.innerHTML = contacts.map(function(c, i) {
            var confidenceBadge = c.email_confidence
                ? '<span class="badge badge-' + c.email_confidence.toLowerCase() + '">' + c.email_confidence + '</span>'
                : '--';
            return '<tr>' +
                '<td>' + (startIdx + i + 1) + '</td>' +
                '<td>' + escapeHtml(c.company || '') + '</td>' +
                '<td><a href="/contacts/' + c.id + '"><strong>' + escapeHtml(c.name) + '</strong></a></td>' +
                '<td class="truncate" style="max-width: 180px;">' + escapeHtml(c.title || '') + '</td>' +
                '<td>' + escapeHtml(c.email) + '</td>' +
                '<td>' + statusBadge(c.status) + '</td>' +
                '<td>' + (c.wave || '--') + '</td>' +
                '<td>' + confidenceBadge + '</td>' +
                '<td><a href="/contacts/' + c.id + '" class="btn btn-sm btn-secondary">View</a></td>' +
            '</tr>';
        }).join('');

        this.renderPagination(total, page, perPage);
    },

    renderPagination: function(total, page, perPage) {
        var container = document.getElementById('contactsPagination');
        if (!container) return;

        var totalPages = Math.ceil(total / perPage);
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        var html = '';
        var self = this;

        // Previous
        if (page > 1) {
            html += '<a href="#" data-page="' + (page - 1) + '">Prev</a>';
        } else {
            html += '<span class="disabled">Prev</span>';
        }

        // Page numbers
        for (var p = 1; p <= totalPages; p++) {
            if (p === page) {
                html += '<span class="active">' + p + '</span>';
            } else {
                html += '<a href="#" data-page="' + p + '">' + p + '</a>';
            }
        }

        // Next
        if (page < totalPages) {
            html += '<a href="#" data-page="' + (page + 1) + '">Next</a>';
        } else {
            html += '<span class="disabled">Next</span>';
        }

        container.innerHTML = html;

        // Bind page clicks
        container.querySelectorAll('a[data-page]').forEach(function(el) {
            el.addEventListener('click', function(e) {
                e.preventDefault();
                self.currentPage = parseInt(this.getAttribute('data-page'));
                self.loadContacts();
            });
        });
    }
};


/* ============================== Contact Detail ============================== */

var ContactDetail = {
    contactId: null,
    contact: null,

    init: function(contactId) {
        this.contactId = contactId;
        this.load();
    },

    load: function() {
        var self = this;
        fetchAPI('/api/contacts/' + this.contactId).then(function(c) {
            self.contact = c;
            self.render(c);
        }).catch(function(err) {
            showNotification('Failed to load contact', 'error');
        });
    },

    render: function(c) {
        // Avatar
        var initials = (c.name || '?').split(' ').map(function(n) { return n[0]; }).join('').toUpperCase().substring(0, 2);
        document.getElementById('contactAvatar').textContent = initials;

        // Header
        document.getElementById('contactName').textContent = c.name;
        document.getElementById('contactTitle').textContent = c.title ? c.title + ' at ' : '';
        document.getElementById('contactCompany').textContent = c.company || '';

        // Badges
        var badges = document.getElementById('contactBadges');
        var badgeHtml = statusBadge(c.status);
        if (c.email_confidence) {
            badgeHtml += ' <span class="badge badge-' + c.email_confidence.toLowerCase() + '">' + c.email_confidence + '</span>';
        }
        if (c.wave) {
            badgeHtml += ' <span class="badge badge-draft">Wave ' + c.wave + '</span>';
        }
        badges.innerHTML = badgeHtml;

        // Editable fields
        document.getElementById('editName').value = c.name || '';
        document.getElementById('editTitle').value = c.title || '';
        document.getElementById('editEmail').value = c.email || '';
        document.getElementById('editCompany').value = c.company || '';

        // Notes
        document.getElementById('contactNotes').value = c.notes || '';
        setupNotesAutosave('contactNotes', this.contactId);

        // Personalization hooks
        var hooksEl = document.getElementById('personalizationHooks');
        if (c.personalization_hooks) {
            try {
                var parsed = typeof c.personalization_hooks === 'string'
                    ? JSON.parse(c.personalization_hooks) : c.personalization_hooks;
                var hookLabels = {
                    suggested_opening_line: 'Suggested Opening',
                    recent_news: 'Recent News',
                    cooling_angle: 'Cooling Angle',
                    contact_hook: 'Contact Hook',
                    academic_connection: 'Academic Connection',
                    unique_detail: 'Unique Detail'
                };
                var html = '';
                var order = ['suggested_opening_line', 'recent_news', 'cooling_angle',
                             'contact_hook', 'academic_connection', 'unique_detail'];
                order.forEach(function(key) {
                    var val = parsed[key];
                    if (val && val !== 'None found.' && val !== 'None found') {
                        html += '<div style="margin-bottom: 10px; padding: 8px 10px; background: #f8f7f2; border-radius: 6px; border-left: 3px solid ' +
                            (key === 'suggested_opening_line' ? '#16a34a' : '#d4a574') + ';">' +
                            '<div style="font-weight: 600; font-size: 0.78rem; text-transform: uppercase; color: #666; margin-bottom: 3px;">' +
                            escapeHtml(hookLabels[key] || key) + '</div>' +
                            '<div>' + escapeHtml(val) + '</div></div>';
                    }
                });
                hooksEl.innerHTML = html || '<p class="text-muted">No personalization hooks set.</p>';
            } catch (e) {
                hooksEl.innerHTML = '<pre style="font-size: 0.82rem; background: #f8f7f2; padding: 12px; border-radius: 6px; white-space: pre-wrap;">' +
                    escapeHtml(c.personalization_hooks) + '</pre>';
            }
        } else {
            hooksEl.innerHTML = '<p class="text-muted">No personalization hooks set.</p>';
        }

        // Email timeline
        this.renderEmailTimeline(c.emails || []);

        // Replies
        this.renderReplies(c.replies || []);
    },

    renderEmailTimeline: function(emails) {
        var container = document.getElementById('emailTimeline');
        if (!emails || emails.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding: 16px;"><p>No emails for this contact yet.</p></div>';
            return;
        }

        var typePriority = { initial: 0, followup1: 1, followup2: 2, manual: 3 };
        emails.sort(function(a, b) {
            return (typePriority[a.email_type] || 99) - (typePriority[b.email_type] || 99);
        });

        container.innerHTML = emails.map(function(e) {
            var statusClass = e.status === 'sent' ? 'sent' : (e.status === 'draft' ? 'draft' : '');
            var canEdit = e.status === 'draft' || e.status === 'scheduled';
            var actions = '';
            if (canEdit) {
                actions = '<a href="/emails/' + e.id + '/preview" class="btn btn-sm btn-secondary">Edit</a> ' +
                    '<button class="btn btn-sm btn-success" onclick="ContactDetail.sendNow(' + e.id + ')">Send Now</button>';
            }

            var metaItems = [];
            metaItems.push(statusBadge(e.status));
            if (e.sent_at) metaItems.push('Sent: ' + formatDate(e.sent_at, true));
            if (e.scheduled_at && !e.sent_at) metaItems.push('Scheduled: ' + formatDate(e.scheduled_at, true));

            return '<div class="timeline-item ' + statusClass + '">' +
                '<div class="timeline-card">' +
                    '<div class="timeline-header">' +
                        '<span>' + statusBadge(e.email_type) + '</span>' +
                        '<div>' + actions + '</div>' +
                    '</div>' +
                    '<div class="timeline-subject">' + escapeHtml(e.subject) + '</div>' +
                    '<div class="timeline-body" id="emailBody_' + e.id + '">' +
                        escapeHtml(e.body || '').substring(0, 200) +
                        (e.body && e.body.length > 200 ? '<span class="expand-toggle" onclick="ContactDetail.expandBody(' + e.id + ', this)">Show more</span>' : '') +
                    '</div>' +
                    '<div class="timeline-meta">' + metaItems.join(' &middot; ') + '</div>' +
                '</div>' +
            '</div>';
        }).join('');
    },

    renderReplies: function(replies) {
        var section = document.getElementById('replySection');
        var content = document.getElementById('replyContent');
        if (!replies || replies.length === 0) {
            section.style.display = 'none';
            return;
        }

        section.style.display = 'block';
        content.innerHTML = replies.map(function(r) {
            return '<div class="card mb-1" style="padding: 14px;">' +
                '<div class="d-flex justify-between align-center mb-1">' +
                    '<strong>' + escapeHtml(r.from_email) + '</strong>' +
                    '<span class="text-muted" style="font-size: 0.78rem;">' + formatRelativeTime(r.received_at) + '</span>' +
                '</div>' +
                (r.subject ? '<div class="text-muted mb-1" style="font-size: 0.85rem;">Re: ' + escapeHtml(r.subject) + '</div>' : '') +
                '<div style="font-size: 0.88rem;">' + escapeHtml(r.snippet || '') + '</div>' +
            '</div>';
        }).join('');
    },

    expandBody: function(emailId, toggleEl) {
        var bodyEl = document.getElementById('emailBody_' + emailId);
        if (!bodyEl) return;

        // If already expanded, find the full body from original data
        if (bodyEl.classList.contains('expanded')) {
            bodyEl.classList.remove('expanded');
            toggleEl.textContent = 'Show more';
        } else {
            // Fetch full email body
            fetchAPI('/api/emails/' + emailId).then(function(email) {
                bodyEl.textContent = email.body || '';
                bodyEl.classList.add('expanded');
            });
        }
    },

    saveContact: function() {
        var data = {
            name: document.getElementById('editName').value.trim(),
            title: document.getElementById('editTitle').value.trim(),
            email: document.getElementById('editEmail').value.trim(),
            company: document.getElementById('editCompany').value.trim()
        };

        fetchAPI('/api/contacts/' + this.contactId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(function(c) {
            showNotification('Contact updated', 'success');
            ContactDetail.render(c);
        }).catch(function(err) {
            showNotification('Update failed: ' + err.message, 'error');
        });
    },

    optOut: function() {
        if (!confirm('Are you sure you want to opt out this contact? All pending emails will be cancelled.')) return;

        fetchAPI('/api/contacts/' + this.contactId + '/opt-out', { method: 'POST' })
        .then(function(data) {
            showNotification('Contact opted out. ' + data.emails_cancelled + ' emails cancelled.', 'info');
            ContactDetail.load();
        }).catch(function(err) {
            showNotification('Opt-out failed: ' + err.message, 'error');
        });
    },

    sendNow: function(emailId) {
        fetchAPI('/api/emails/' + emailId + '/send-now', { method: 'POST' })
        .then(function(data) {
            showNotification('Email sent', 'success');
            ContactDetail.load();
        }).catch(function(err) {
            showNotification('Send failed: ' + err.message, 'error');
        });
    },

    toggleCollapsible: function(headerEl) {
        headerEl.classList.toggle('open');
        var body = headerEl.nextElementSibling;
        if (body) body.classList.toggle('open');
    }
};


/* ============================== Contact Form ============================== */

var ContactForm = {
    init: function() {
        this.loadCampaigns();
    },

    loadCampaigns: function() {
        fetchAPI('/api/campaigns').then(function(campaigns) {
            var selects = [
                document.getElementById('formCampaignId'),
                document.getElementById('jsonCampaignId')
            ];
            selects.forEach(function(select) {
                if (!select) return;
                campaigns.forEach(function(c) {
                    var opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    select.appendChild(opt);
                });
            });
        });
    },

    switchTab: function(btn) {
        // Deactivate all tabs
        document.querySelectorAll('.tab-btn').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });

        // Activate clicked tab
        btn.classList.add('active');
        var tabId = btn.getAttribute('data-tab');
        document.getElementById(tabId).classList.add('active');
    },

    submitForm: function(e) {
        e.preventDefault();
        var campaignId = document.getElementById('formCampaignId').value;
        if (!campaignId) {
            showNotification('Please select a campaign', 'warning');
            return;
        }

        var data = {
            campaign_id: parseInt(campaignId),
            name: document.getElementById('formName').value.trim(),
            email: document.getElementById('formEmail').value.trim(),
            company: document.getElementById('formCompany').value.trim(),
            title: document.getElementById('formTitle').value.trim(),
            email_confidence: document.getElementById('formConfidence').value || null,
            wave: document.getElementById('formWave').value ? parseInt(document.getElementById('formWave').value) : null,
            ask_type: document.getElementById('formAskType').value || null,
            notes: document.getElementById('formNotes').value.trim() || null
        };

        fetchAPI('/api/contacts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(function(contact) {
            showNotification('Contact created successfully', 'success');
            setTimeout(function() {
                window.location.href = '/contacts/' + contact.id;
            }, 500);
        }).catch(function(err) {
            showNotification('Failed to create contact: ' + err.message, 'error');
        });
    },

    validateJSON: function() {
        var input = document.getElementById('jsonInput').value.trim();
        try {
            var parsed = JSON.parse(input);
            if (Array.isArray(parsed)) {
                showNotification('Valid JSON array with ' + parsed.length + ' contacts', 'success');
            } else if (typeof parsed === 'object') {
                showNotification('Valid JSON object (1 contact)', 'success');
            } else {
                showNotification('JSON must be an object or array of objects', 'error');
            }
        } catch (e) {
            showNotification('Invalid JSON: ' + e.message, 'error');
        }
    },

    submitJSON: function() {
        var campaignId = document.getElementById('jsonCampaignId').value;
        if (!campaignId) {
            showNotification('Please select a campaign', 'warning');
            return;
        }

        var input = document.getElementById('jsonInput').value.trim();
        var contacts;
        try {
            contacts = JSON.parse(input);
            if (!Array.isArray(contacts)) contacts = [contacts];
        } catch (e) {
            showNotification('Invalid JSON: ' + e.message, 'error');
            return;
        }

        // Add campaign_id to each contact
        contacts = contacts.map(function(c) {
            c.campaign_id = parseInt(campaignId);
            return c;
        });

        fetchAPI('/api/contacts/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(contacts)
        }).then(function(data) {
            showNotification('Created ' + data.total_created + ' contacts' +
                (data.errors.length > 0 ? ' (' + data.errors.length + ' errors)' : ''), 'success');
            setTimeout(function() {
                window.location.href = '/contacts';
            }, 1000);
        }).catch(function(err) {
            showNotification('Import failed: ' + err.message, 'error');
        });
    }
};


/* ============================== Import Manager ============================== */

var ImportManager = {
    previewData: [],
    jsonData: null,

    init: function() {
        this.loadCampaigns();
    },

    loadCampaigns: function() {
        fetchAPI('/api/campaigns').then(function(campaigns) {
            var selects = [
                document.getElementById('importCampaignId'),
                document.getElementById('jsonImportCampaignId')
            ];
            selects.forEach(function(select) {
                if (!select) return;
                campaigns.forEach(function(c) {
                    var opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    select.appendChild(opt);
                });
            });
        });
    },

    preview: function() {
        var filepath = document.getElementById('importFilepath').value.trim();
        if (!filepath) {
            showNotification('Please enter a file path', 'warning');
            return;
        }

        showNotification('File path set: ' + filepath + '. Click "Import Selected" to proceed.', 'info');
        document.getElementById('btnImportSelected').disabled = false;
    },

    importSelected: function() {
        var filepath = document.getElementById('importFilepath').value.trim();
        var campaignId = document.getElementById('importCampaignId').value;

        if (!filepath) {
            showNotification('Please enter a file path', 'warning');
            return;
        }

        var data = { filepath: filepath };
        if (campaignId) data.campaign_id = parseInt(campaignId);

        fetchAPI('/api/contacts/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(function(result) {
            ImportManager._showResults(result);
        }).catch(function(err) {
            showNotification('Import failed: ' + err.message, 'error');
        });
    },

    // --- JSON File Upload ---

    previewJSON: function() {
        var fileInput = document.getElementById('jsonFileInput');
        if (!fileInput || !fileInput.files.length) {
            showNotification('Please select a JSON file', 'warning');
            return;
        }

        var reader = new FileReader();
        reader.onload = function(e) {
            try {
                var data = JSON.parse(e.target.result);
                ImportManager.jsonData = data;
                var contacts = data.contacts || [];
                if (contacts.length === 0) {
                    showNotification('No contacts found in JSON file', 'warning');
                    return;
                }

                // Render preview table
                ImportManager._renderPreview(contacts);
                document.getElementById('btnImportJSON').disabled = false;
                showNotification('Loaded ' + contacts.length + ' contacts. Review and click Import.', 'success');
            } catch (err) {
                showNotification('Invalid JSON: ' + err.message, 'error');
            }
        };
        reader.readAsText(fileInput.files[0]);
    },

    importJSON: function() {
        if (!this.jsonData) {
            showNotification('No JSON data loaded. Click Preview first.', 'warning');
            return;
        }

        // Collect selected external_ids
        var selectedIds = new Set();
        document.querySelectorAll('.import-checkbox:checked').forEach(function(cb) {
            selectedIds.add(cb.value);
        });

        if (selectedIds.size === 0) {
            showNotification('No contacts selected for import', 'warning');
            return;
        }

        // Filter contacts to only selected ones
        var payload = {
            campaign: this.jsonData.campaign || {},
            contacts: this.jsonData.contacts.filter(function(c) {
                return selectedIds.has(String(c.external_id));
            })
        };

        var campaignId = document.getElementById('jsonImportCampaignId').value;
        if (campaignId) payload.campaign_id = parseInt(campaignId);

        fetchAPI('/api/contacts/import-json', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(result) {
            ImportManager._showResults(result);
        }).catch(function(err) {
            showNotification('Import failed: ' + err.message, 'error');
        });
    },

    // --- Shared helpers ---

    _renderPreview: function(contacts) {
        var section = document.getElementById('previewSection');
        var tbody = document.getElementById('previewTableBody');
        var count = document.getElementById('previewCount');

        section.style.display = 'block';
        count.textContent = contacts.length;

        tbody.innerHTML = contacts.map(function(c) {
            var confidenceBadge = c.email_confidence
                ? '<span class="badge badge-' + c.email_confidence.toLowerCase() + '">' + c.email_confidence + '</span>'
                : '--';
            var hasHooks = c.personalization_hooks && c.personalization_hooks.length > 2;
            var hooksIndicator = hasHooks ? ' <span title="Has personalization hooks" style="color: #16a34a;">&#9679;</span>' : '';
            return '<tr>' +
                '<td><input type="checkbox" class="import-checkbox" value="' + escapeHtml(String(c.external_id)) + '" checked></td>' +
                '<td>' + escapeHtml(c.name || '') + hooksIndicator + '</td>' +
                '<td>' + escapeHtml(c.company || '') + '</td>' +
                '<td>' + escapeHtml(c.email || '') + '</td>' +
                '<td class="truncate" style="max-width: 150px;">' + escapeHtml(c.title || '') + '</td>' +
                '<td>' + (c.wave || '--') + '</td>' +
            '</tr>';
        }).join('');

        // Check master checkbox
        document.getElementById('selectAllCheckbox').checked = true;
    },

    _showResults: function(result) {
        var resultsDiv = document.getElementById('importResults');
        var resultsBody = document.getElementById('importResultsBody');
        resultsDiv.style.display = 'block';
        resultsBody.innerHTML =
            '<p><strong>Contacts Created:</strong> ' + result.contacts_created + '</p>' +
            '<p><strong>Emails Created:</strong> ' + result.emails_created + '</p>' +
            '<p><strong>Skipped:</strong> ' + result.skipped + '</p>' +
            (result.campaign_id ? '<p><strong>Campaign ID:</strong> ' + result.campaign_id + '</p>' : '') +
            '<div class="mt-2"><a href="/contacts" class="btn btn-primary">View Contacts</a></div>';
        showNotification('Import complete: ' + result.contacts_created + ' contacts created', 'success');
    },

    selectAll: function() {
        document.querySelectorAll('.import-checkbox').forEach(function(cb) { cb.checked = true; });
        document.getElementById('selectAllCheckbox').checked = true;
    },

    deselectAll: function() {
        document.querySelectorAll('.import-checkbox').forEach(function(cb) { cb.checked = false; });
        document.getElementById('selectAllCheckbox').checked = false;
    },

    toggleAll: function(masterCheckbox) {
        document.querySelectorAll('.import-checkbox').forEach(function(cb) {
            cb.checked = masterCheckbox.checked;
        });
    }
};
