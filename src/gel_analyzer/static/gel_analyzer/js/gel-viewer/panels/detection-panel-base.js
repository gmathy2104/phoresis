/**
 * detection-panel-base.js
 *
 * Shared base utilities for the detection panels (DetectionPanel, CV2DetectionPanel,
 * BandModelPanel). Provides common slider binding, teacher integration, show/hide
 * animation, lane filtering, taught-badge management, and task polling.
 *
 * This is NOT a class to inherit from — it's a namespace of static helpers
 * that the panels call, passing their own state as arguments.
 *
 * @requires GelViewer.Events
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * DetectionPanelBase — shared utilities for detection panels.
     */
    const DetectionPanelBase = {

        // ─── Slider Binding ──────────────────────────────────────────

        /**
         * Bind a slider element to a parameter key on the given params object.
         * @param {string} sliderId - DOM id of the range input
         * @param {string} paramKey - Key in params object
         * @param {Object} params - Mutable params object
         * @param {Function} [formatFn] - Optional value formatter (key, value) => string
         * @param {Function} [onChange] - Optional callback after value change
         */
        bindSlider(sliderId, paramKey, params, formatFn, onChange) {
            const slider = document.getElementById(sliderId);
            const valueDisplay = document.getElementById(`${sliderId}-value`);

            if (slider) {
                slider.addEventListener('input', () => {
                    const value = parseFloat(slider.value);
                    params[paramKey] = value;

                    if (valueDisplay) {
                        valueDisplay.textContent = formatFn
                            ? formatFn(paramKey, value)
                            : String(value);
                    }

                    if (onChange) onChange(paramKey, value);
                });
            }
        },

        /**
         * Sync slider positions to current param values.
         * @param {Array<[string, string]>} sliderMap - Array of [sliderId, paramKey] pairs
         * @param {Object} params - Current params object
         * @param {Function} [formatFn] - Optional value formatter
         */
        syncSlidersToParams(sliderMap, params, formatFn) {
            for (const [sliderId, paramKey] of sliderMap) {
                const slider = document.getElementById(sliderId);
                const valueDisplay = document.getElementById(`${sliderId}-value`);

                if (slider && params[paramKey] !== undefined) {
                    slider.value = params[paramKey];
                    if (valueDisplay) {
                        valueDisplay.textContent = formatFn
                            ? formatFn(paramKey, params[paramKey])
                            : String(params[paramKey]);
                    }
                }
            }
        },

        // ─── Taught Badge Management ─────────────────────────────────

        /**
         * Add "T" badges to sliders whose values came from the teacher.
         * @param {Object} sliderParamMap - { sliderId: paramKey } mapping
         * @param {Set|null} taughtKeys - Set of taught param keys
         */
        markTaughtSliders(sliderParamMap, taughtKeys) {
            for (const [sliderId, paramKey] of Object.entries(sliderParamMap)) {
                const valueDisplay = document.getElementById(`${sliderId}-value`);
                if (!valueDisplay) continue;

                // Remove existing badge
                const existing = valueDisplay.parentElement.querySelector('.gv-taught-badge');
                if (existing) existing.remove();

                // Add badge if this param was taught
                if (taughtKeys && taughtKeys.has(paramKey)) {
                    const badge = document.createElement('span');
                    badge.className = 'gv-taught-badge';
                    badge.title = 'Set by Teacher';
                    badge.textContent = 'T';
                    valueDisplay.parentElement.appendChild(badge);
                }
            }
        },

        /**
         * Remove all taught badges from a panel element.
         * @param {HTMLElement} panelEl - Panel DOM element
         * @returns {null} New value for _taughtKeys
         */
        clearTaughtBadges(panelEl) {
            if (panelEl) {
                panelEl.querySelectorAll('.gv-taught-badge').forEach(b => b.remove());
            }
            return null;
        },

        // ─── Teacher Integration ─────────────────────────────────────

        /**
         * Setup teacher panel event subscriptions for a detection panel.
         * @param {EventBus} eventBus
         * @param {Object} panel - Panel instance (needs isVisible, show, hide, _wasVisibleBeforeTeacher)
         */
        setupTeacherEvents(eventBus, panel) {
            eventBus.on(Events.TEACHER_PANEL_SHOWN, () => {
                // Emitted twice (the Teach button, then TeacherPanel.show): only a visible panel sets the flag, or
                // the second emit forgot it and the panel never came back when the teacher closed.
                if (panel.isVisible) {
                    panel._wasVisibleBeforeTeacher = true;
                    panel.hide();
                }
            });

            eventBus.on(Events.TEACHER_PANEL_HIDDEN, () => {
                if (panel._wasVisibleBeforeTeacher) panel.show();
                panel._wasVisibleBeforeTeacher = false;
            });
        },

        // ─── Show / Hide with Animation ──────────────────────────────

        /**
         * Show a panel with fade-in animation.
         * @param {HTMLElement} panelEl - Panel element
         * @param {HTMLElement} backdropEl - Backdrop element
         */
        showPanel(panelEl, backdropEl) {
            if (backdropEl) {
                backdropEl.style.display = 'block';
            }
            if (panelEl) {
                panelEl.style.display = 'flex';
                // Force reflow for CSS transition
                panelEl.offsetHeight;
                requestAnimationFrame(() => {
                    if (backdropEl) backdropEl.classList.add('open');
                    panelEl.classList.add('open');
                });
            }
        },

        /**
         * Hide a panel with fade-out animation.
         * Uses a guard flag to prevent show() during the animation window.
         * @param {HTMLElement} panelEl - Panel element
         * @param {HTMLElement} backdropEl - Backdrop element
         * @param {Function} onComplete - Called after animation completes (for setting isVisible)
         * @returns {number} setTimeout ID (for cancellation if needed)
         */
        hidePanel(panelEl, backdropEl, onComplete) {
            if (panelEl) {
                panelEl.classList.remove('open');
            }
            if (backdropEl) {
                backdropEl.classList.remove('open');
            }

            return setTimeout(() => {
                if (panelEl) panelEl.style.display = 'none';
                if (backdropEl) backdropEl.style.display = 'none';
                if (onComplete) onComplete();
            }, 350);
        },

        // ─── Lane Filtering ──────────────────────────────────────────

        /**
         * Compute target lanes based on filter value.
         * @param {string} laneFilter - 'all', 'sample', 'ladder', 'selected'
         * @param {Object} stateManager - StateManager instance
         * @returns {Array} Filtered lane objects
         */
        getTargetLanes(laneFilter, stateManager) {
            const lanesMap = stateManager?.getAllLanes();
            const allLanes = lanesMap ? Array.from(lanesMap.values()) : [];

            switch (laneFilter) {
                case 'ladder':
                    return allLanes.filter(l => l.lane_type === 'LADDER');
                case 'sample':
                    return allLanes.filter(l => l.lane_type === 'SAMPLE');
                case 'selected': {
                    const selection = stateManager?.getSelection();
                    const selectedId = selection?.type === 'lane' ? selection.id : null;
                    const selectedLane = allLanes.find(l => l.id === selectedId);
                    return selectedLane ? [selectedLane] : [];
                }
                case 'all':
                default:
                    return allLanes;
            }
        },

        // ─── Task Polling ────────────────────────────────────────────

        /**
         * Poll a Celery task until completion, calling progress callbacks.
         * @param {Object} apiClient - API client with getTaskStatus()
         * @param {string} taskId - Celery task ID
         * @param {number} totalLanes - Total lanes for progress display
         * @param {Object} [options]
         * @param {number} [options.intervalMs=500] - Poll interval
         * @param {number} [options.maxAttempts=600] - Max poll attempts (5 min at 500ms)
         * @param {Function} [options.onProgress] - Called with (current, total) on progress
         * @param {string} [options.logPrefix='DetectionPanel'] - Log prefix
         * @returns {Promise<Object>} Task result on success
         */
        async pollTaskStatus(apiClient, taskId, totalLanes, options = {}) {
            const {
                intervalMs = 500,
                maxAttempts = 600,
                onProgress = null,
                logPrefix = 'DetectionPanel',
            } = options;

            let attempts = 0;

            while (attempts < maxAttempts) {
                const status = await apiClient.getTaskStatus(taskId);

                if (status.state === 'SUCCESS') {
                    if (status.result?.success === false) {
                        throw new Error(status.result?.error || 'Detection failed');
                    }
                    console.log(`[${logPrefix}] Task completed:`, status.result);
                    return status.result;
                }

                if (status.state === 'FAILURE') {
                    throw new Error(status.result?.error || status.error || 'Task failed');
                }

                if (status.state === 'PROGRESS' && status.result && onProgress) {
                    const current = status.result.current || 0;
                    const total = status.result.total || totalLanes;
                    onProgress(current, total);
                }

                await new Promise(resolve => setTimeout(resolve, intervalMs));
                attempts++;
            }

            throw new Error('Detection task timed out');
        },

        // ─── Electropherogram Embedding ──────────────────────────────

        /**
         * Embed the electropherogram panel into a chart host container.
         * @param {Object} epgramPanel - ElectropherogramPanel instance
         * @param {string} chartHostId - DOM id of the chart host container
         * @param {string} placeholderId - DOM id of the placeholder element
         * @returns {Object|null} Embed state for later unembed, or null if failed
         */
        embedElectropherogram(epgramPanel, chartHostId, placeholderId) {
            if (!epgramPanel) return null;

            const epPanel = epgramPanel.panel;
            const chartHost = document.getElementById(chartHostId);

            if (!epPanel || !chartHost) return null;

            // Save original parent and display state
            const embedState = {
                originalParent: epPanel.parentElement,
                originalDisplay: epPanel.style.display,
                _dimWaitRAF: null,
                _dimWaitTimer: null,
            };

            // Reparent into chart host
            chartHost.appendChild(epPanel);
            epPanel.classList.add('gv-embedded');
            epPanel.style.display = 'flex';

            // Mark as visible so it accepts profile loads
            epgramPanel.isVisible = true;

            // Hide chart placeholder
            const placeholder = document.getElementById(placeholderId);
            if (placeholder) placeholder.style.display = 'none';

            // Wait for dimensions then trigger Plotly relayout
            DetectionPanelBase._waitForChartDimensions(epgramPanel, embedState, () => {
                const chartContainer = epgramPanel.chartContainer;
                if (!chartContainer) return;

                try {
                    if (epgramPanel.plotInitialized) {
                        Plotly.relayout(chartContainer, {
                            'xaxis.autorange': true,
                            'yaxis.autorange': true,
                        });
                    } else if (epgramPanel.profileData) {
                        epgramPanel._render();
                    }
                } catch (e) {
                    console.error('[DetectionPanelBase] Plotly embed relayout error:', e);
                }
            });

            return embedState;
        },

        /**
         * Return the electropherogram panel to its original location.
         * @param {Object} epgramPanel - ElectropherogramPanel instance
         * @param {Object} embedState - State returned from embedElectropherogram
         * @param {string} placeholderId - DOM id of the placeholder element
         */
        unembedElectropherogram(epgramPanel, embedState, placeholderId) {
            if (!epgramPanel || !embedState) return;

            // Cancel any pending dimension wait
            DetectionPanelBase._cancelWaitForDimensions(embedState);

            const epPanel = epgramPanel.panel;
            if (!epPanel || !embedState.originalParent) return;

            // Set reparenting flag to prevent reload race
            epgramPanel._reparenting = true;

            // Return to original parent
            embedState.originalParent.appendChild(epPanel);
            epPanel.classList.remove('gv-embedded');

            // Restore original display state
            epPanel.style.display = embedState.originalDisplay || 'none';
            epgramPanel.isVisible = (embedState.originalDisplay !== 'none');

            // Show chart placeholder again
            const placeholder = document.getElementById(placeholderId);
            if (placeholder) placeholder.style.display = '';

            // Trigger Plotly relayout after reparent — double-rAF to wait for layout
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    epgramPanel._reparenting = false;
                    const chartContainer = epgramPanel.chartContainer;
                    if (chartContainer && epgramPanel.plotInitialized && epgramPanel.isVisible) {
                        try {
                            Plotly.relayout(chartContainer, {
                                'xaxis.autorange': true,
                                'yaxis.autorange': true,
                            });
                        } catch (e) {
                            console.error('[DetectionPanelBase] Plotly unembed relayout error:', e);
                        }
                    }
                });
            });
        },

        /**
         * Wait for chart container to have valid dimensions.
         * @private
         */
        _waitForChartDimensions(epgramPanel, embedState, callback, attempt) {
            attempt = attempt || 0;

            if (attempt === 0) {
                DetectionPanelBase._cancelWaitForDimensions(embedState);
            }

            const chartContainer = epgramPanel && epgramPanel.chartContainer;
            if (!chartContainer) return;

            const rect = chartContainer.getBoundingClientRect();
            if (rect.width >= 1 && rect.height >= 1) {
                callback();
                return;
            }

            if (attempt >= 15) {
                console.warn('[DetectionPanelBase] Gave up waiting for chart dimensions after 15 attempts');
                callback();
                return;
            }

            if (attempt <= 1) {
                embedState._dimWaitRAF = requestAnimationFrame(() => {
                    embedState._dimWaitRAF = requestAnimationFrame(() => {
                        embedState._dimWaitRAF = null;
                        DetectionPanelBase._waitForChartDimensions(epgramPanel, embedState, callback, attempt + 1);
                    });
                });
            } else {
                const delay = 50 * Math.pow(2, attempt - 2);
                embedState._dimWaitTimer = setTimeout(() => {
                    embedState._dimWaitTimer = null;
                    DetectionPanelBase._waitForChartDimensions(epgramPanel, embedState, callback, attempt + 1);
                }, delay);
            }
        },

        /**
         * Cancel any pending dimension wait.
         * @private
         */
        _cancelWaitForDimensions(embedState) {
            if (!embedState) return;
            if (embedState._dimWaitRAF) {
                cancelAnimationFrame(embedState._dimWaitRAF);
                embedState._dimWaitRAF = null;
            }
            if (embedState._dimWaitTimer) {
                clearTimeout(embedState._dimWaitTimer);
                embedState._dimWaitTimer = null;
            }
        },

        // ─── Progress UI ─────────────────────────────────────────────

        /**
         * Show progress bar with current/total.
         * @param {string} progressId - DOM id of progress container
         * @param {string} fillId - DOM id of progress fill bar
         * @param {string} textId - DOM id of progress text
         * @param {number} current
         * @param {number} total
         */
        showProgress(progressId, fillId, textId, current, total) {
            const progressEl = document.getElementById(progressId);
            const fillEl = document.getElementById(fillId);
            const textEl = document.getElementById(textId);

            if (progressEl) progressEl.style.display = 'block';

            if (fillEl) {
                const percent = total > 0 ? (current / total) * 100 : 0;
                fillEl.style.width = `${percent}%`;
            }

            if (textEl) {
                textEl.textContent = `Processing lane ${current}/${total}...`;
            }
        },

        /**
         * Hide progress bar.
         * @param {string} progressId - DOM id of progress container
         */
        hideProgress(progressId) {
            const progressEl = document.getElementById(progressId);
            if (progressEl) progressEl.style.display = 'none';
        },
    };

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.DetectionPanelBase = DetectionPanelBase;

})(window);
