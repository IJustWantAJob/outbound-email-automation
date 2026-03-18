/* ======================================================================
   Email Campaign Manager -- Dashboard Charts & Metrics
   ====================================================================== */

var Dashboard = {
    sentChart: null,
    repliesChart: null,
    statusChart: null,
    refreshInterval: null,

    init: function() {
        this.loadData();
        this.loadQueue();
        this.loadActivity();
        // Auto-refresh every 60 seconds
        this.refreshInterval = setInterval(function() {
            Dashboard.loadData();
            Dashboard.loadQueue();
            Dashboard.loadActivity();
        }, 60000);
    },

    loadData: function() {
        fetchAPI('/api/metrics/dashboard').then(function(data) {
            Dashboard.updateMetricCards(data);
            Dashboard.renderSentByDayChart(data.sent_by_day || []);
            Dashboard.renderRepliesCumulativeChart(data.replies_by_day || []);
            Dashboard.renderContactStatusChart(data.contacts_by_status || {});
        }).catch(function(err) {
            console.error('Failed to load dashboard metrics:', err);
        });
    },

    updateMetricCards: function(data) {
        // Total Sent
        var sentEl = document.getElementById('metricTotalSent');
        animateCounter(sentEl, data.total_sent || 0);
        document.getElementById('metricBouncedSub').textContent =
            (data.total_bounced || 0) + ' bounced';

        // Response Rate
        var rateEl = document.getElementById('metricResponseRate');
        animateCounter(rateEl, Math.round(data.response_rate || 0), '%');
        document.getElementById('metricRepliedSub').textContent =
            (data.total_replied || 0) + ' replies received';

        // Avg Response Time
        var avgEl = document.getElementById('metricAvgResponseTime');
        avgEl.textContent = (data.avg_response_time_hours || 0).toFixed(1);

        // Active Contacts
        var contactsEl = document.getElementById('metricActiveContacts');
        animateCounter(contactsEl, data.total_contacts || 0);
        document.getElementById('metricContactsSub').textContent = 'total in system';
    },

    renderSentByDayChart: function(sentByDay) {
        var ctx = document.getElementById('sentByDayChart');
        if (!ctx) return;

        var labels = sentByDay.map(function(d) { return d.date; });
        var values = sentByDay.map(function(d) { return d.count; });

        if (Dashboard.sentChart) {
            Dashboard.sentChart.data.labels = labels;
            Dashboard.sentChart.data.datasets[0].data = values;
            Dashboard.sentChart.update();
            return;
        }

        Dashboard.sentChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels.length ? labels : ['No data'],
                datasets: [{
                    label: 'Emails Sent',
                    data: values.length ? values : [0],
                    backgroundColor: 'rgba(212, 163, 115, 0.6)',
                    borderColor: '#d4a373',
                    borderWidth: 1,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, color: '#6b6b5e' },
                        grid: { color: 'rgba(213, 208, 196, 0.3)' }
                    },
                    x: {
                        ticks: { color: '#6b6b5e' },
                        grid: { display: false }
                    }
                }
            }
        });
    },

    renderRepliesCumulativeChart: function(repliesByDay) {
        var ctx = document.getElementById('repliesCumulativeChart');
        if (!ctx) return;

        // Convert to cumulative
        var labels = repliesByDay.map(function(d) { return d.date; });
        var cumulative = [];
        var sum = 0;
        repliesByDay.forEach(function(d) {
            sum += d.count;
            cumulative.push(sum);
        });

        if (Dashboard.repliesChart) {
            Dashboard.repliesChart.data.labels = labels;
            Dashboard.repliesChart.data.datasets[0].data = cumulative;
            Dashboard.repliesChart.update();
            return;
        }

        Dashboard.repliesChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels.length ? labels : ['No data'],
                datasets: [{
                    label: 'Cumulative Replies',
                    data: cumulative.length ? cumulative : [0],
                    borderColor: '#5a8a5e',
                    backgroundColor: 'rgba(90, 138, 94, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointBackgroundColor: '#5a8a5e',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, color: '#6b6b5e' },
                        grid: { color: 'rgba(213, 208, 196, 0.3)' }
                    },
                    x: {
                        ticks: { color: '#6b6b5e' },
                        grid: { display: false }
                    }
                }
            }
        });
    },

    renderContactStatusChart: function(contactsByStatus) {
        var ctx = document.getElementById('contactStatusChart');
        if (!ctx) return;

        var statusColors = {
            pending: '#faedcd',
            initial_sent: '#d4e8d5',
            followup1_sent: '#c2ddc4',
            followup2_sent: '#afd3b2',
            replied: '#6b8a9e',
            bounced: '#b85c5c',
            opted_out: '#d5d0c4'
        };

        var labels = Object.keys(contactsByStatus);
        var values = labels.map(function(k) { return contactsByStatus[k]; });
        var colors = labels.map(function(k) { return statusColors[k] || '#d5d0c4'; });

        if (Dashboard.statusChart) {
            Dashboard.statusChart.data.labels = labels;
            Dashboard.statusChart.data.datasets[0].data = values;
            Dashboard.statusChart.data.datasets[0].backgroundColor = colors;
            Dashboard.statusChart.update();
            return;
        }

        Dashboard.statusChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels.length ? labels : ['No data'],
                datasets: [{
                    data: values.length ? values : [0],
                    backgroundColor: colors.length ? colors : ['#d5d0c4'],
                    borderWidth: 0,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, color: '#6b6b5e' },
                        grid: { color: 'rgba(213, 208, 196, 0.3)' }
                    },
                    y: {
                        ticks: { color: '#6b6b5e' },
                        grid: { display: false }
                    }
                }
            }
        });
    },

    loadQueue: function() {
        fetchAPI('/api/emails/queue').then(function(queue) {
            var container = document.getElementById('upcomingQueue');
            if (!queue || queue.length === 0) {
                container.innerHTML = '<div class="empty-state" style="padding: 24px;"><p>No upcoming emails scheduled.</p></div>';
                return;
            }
            // Show only next 5
            var items = queue.slice(0, 5);
            container.innerHTML = items.map(function(item) {
                var time = item.scheduled_at ? formatDate(item.scheduled_at, true) : 'Pending';
                return '<div class="activity-item">' +
                    '<span class="activity-dot scheduled"></span>' +
                    '<span class="activity-text">' +
                        '<strong>' + escapeHtml(item.contact_name || 'Contact #' + item.contact_id) + '</strong> ' +
                        '- ' + escapeHtml(item.subject || 'No subject') +
                    '</span>' +
                    '<span class="activity-time">' + time + '</span>' +
                '</div>';
            }).join('');
        }).catch(function() {
            document.getElementById('upcomingQueue').innerHTML =
                '<div class="empty-state" style="padding: 24px;"><p>Could not load queue.</p></div>';
        });
    },

    loadActivity: function() {
        // Load recent sent emails and replies as activity
        Promise.all([
            fetchAPI('/api/emails?status=sent').catch(function() { return []; }),
            fetchAPI('/api/replies').catch(function() { return []; })
        ]).then(function(results) {
            var emails = results[0] || [];
            var replies = results[1] || [];

            var activities = [];

            // Add sent emails as activities
            emails.forEach(function(e) {
                activities.push({
                    type: 'sent',
                    text: 'Email sent to Contact #' + e.contact_id,
                    detail: e.subject,
                    time: e.sent_at
                });
            });

            // Add replies as activities
            replies.forEach(function(r) {
                activities.push({
                    type: 'replied',
                    text: 'Reply from ' + (r.from_email || 'unknown'),
                    detail: r.snippet,
                    time: r.received_at
                });
            });

            // Sort by time descending
            activities.sort(function(a, b) {
                return new Date(b.time || 0) - new Date(a.time || 0);
            });

            var container = document.getElementById('recentActivity');
            if (activities.length === 0) {
                container.innerHTML = '<div class="empty-state" style="padding: 24px;"><p>No recent activity.</p></div>';
                return;
            }

            // Show last 10
            container.innerHTML = '<div class="activity-list">' +
                activities.slice(0, 10).map(function(a) {
                    return '<div class="activity-item">' +
                        '<span class="activity-dot ' + a.type + '"></span>' +
                        '<span class="activity-text">' + escapeHtml(a.text) + '</span>' +
                        '<span class="activity-time">' + formatRelativeTime(a.time) + '</span>' +
                    '</div>';
                }).join('') +
            '</div>';
        });
    }
};


document.addEventListener('DOMContentLoaded', function() {
    Dashboard.init();
});
