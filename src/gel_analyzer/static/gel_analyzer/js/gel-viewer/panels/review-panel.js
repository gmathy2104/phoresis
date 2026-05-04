/**
 * review-panel.js
 *
 * Detection Review Panel for YOLO inference results.
 * Allows users to accept/reject/edit detected lanes before saving.
 *
 * @requires GelViewer.EventBus
 * @requires SVG.js (for preview rendering)
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * ReviewPanel Class
     *
     * UI panel for reviewing and accepting YOLO detections.
     */
    class ReviewPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Object} options.svg - SVG.js instance
         * @param {Function} options.onAccept - Callback when detections are accepted
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.onAccept = options.onAccept;

            // State
            this.detections = [];
            this.selectedIndices = new Set();
            this.inferredGelType = 'UNKNOWN';
            this.isVisible = false;

            // DOM references
            this.panel = null;
            this.listContainer = null;
            this.summaryContainer = null;

            // SVG preview group
            this.previewGroup = null;

            // Initialize
            this._setupDOM();
            this._bindEvents();
        }

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('review-panel');
            this.listContainer = document.getElementById('review-list');
            this.summaryContainer = document.querySelector('.gv-review-summary');

            // Create SVG group for detection previews
            if (this.svg) {
                this.previewGroup = this.svg.group().attr('id', 'detection-previews');
            }
        }

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Close button
            const closeBtn = document.getElementById('review-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Accept all button
            const acceptAllBtn = document.getElementById('review-accept-all');
            if (acceptAllBtn) {
                acceptAllBtn.addEventListener('click', () => this.acceptAll());
            }

            // Accept selected button
            const acceptSelectedBtn = document.getElementById('review-accept-selected');
            if (acceptSelectedBtn) {
                acceptSelectedBtn.addEventListener('click', () => this.acceptSelected());
            }

            // Reject all button
            const rejectAllBtn = document.getElementById('review-reject-all');
            if (rejectAllBtn) {
                rejectAllBtn.addEventListener('click', () => this.rejectAll());
            }

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (!this.isVisible) return;

                if (e.key === 'Escape') {
                    this.hide();
                } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    this.acceptSelected();
                }
            });
        }

        /**
         * Show the review panel with detections.
         * @param {Array<Object>} detections - YOLO detection results
         * @param {string} inferredGelType - Inferred gel type
         */
        show(detections, inferredGelType) {
            this.detections = detections;
            this.inferredGelType = inferredGelType;

            // Select all by default
            this.selectedIndices = new Set(detections.map((_, i) => i));

            // Render UI
            this._renderSummary();
            this._renderDetectionList();
            this._renderPreviews();

            // Show panel
            if (this.panel) {
                this.panel.style.display = 'flex';
            }

            this.isVisible = true;

            // Emit event
            this.eventBus.emit(Events.REVIEW_SHOWN, {
                count: detections.length,
                inferredGelType,
            });
        }

        /**
         * Hide the review panel.
         */
        hide() {
            if (this.panel) {
                this.panel.style.display = 'none';
            }

            // Clear previews
            this._clearPreviews();

            this.isVisible = false;
            this.detections = [];
            this.selectedIndices.clear();

            // Emit event
            this.eventBus.emit(Events.REVIEW_HIDDEN);
        }

        /**
         * Accept all detections.
         */
        acceptAll() {
            if (this.detections.length === 0) return;

            // Select all
            this.selectedIndices = new Set(this.detections.map((_, i) => i));

            // Accept
            this._acceptDetections();
        }

        /**
         * Accept only selected detections.
         */
        acceptSelected() {
            if (this.selectedIndices.size === 0) {
                this._showMessage('No detections selected');
                return;
            }

            this._acceptDetections();
        }

        /**
         * Reject all and close.
         */
        rejectAll() {
            this.hide();

            // Emit event
            this.eventBus.emit(Events.REVIEW_REJECTED, {
                count: this.detections.length,
            });
        }

        /**
         * Toggle selection of a detection.
         * @param {number} index - Detection index
         */
        toggleSelection(index) {
            if (this.selectedIndices.has(index)) {
                this.selectedIndices.delete(index);
            } else {
                this.selectedIndices.add(index);
            }

            this._updateSelectionUI(index);
            this._updateAcceptButton();
        }

        /**
         * Accept selected detections and close.
         */
        _acceptDetections() {
            const accepted = this.detections.filter((_, i) => this.selectedIndices.has(i));

            // Call accept callback
            if (this.onAccept && accepted.length > 0) {
                this.onAccept(accepted, this.inferredGelType);
            }

            // Emit event
            this.eventBus.emit(Events.REVIEW_ACCEPTED, {
                count: accepted.length,
                inferredGelType: this.inferredGelType,
            });

            // Close panel
            this.hide();
        }

        /**
         * Render the summary section.
         */
        _renderSummary() {
            const gelTypeEl = document.getElementById('review-gel-type');
            const countEl = document.getElementById('review-count');

            if (gelTypeEl) {
                const gelTypeDisplay = this._getGelTypeDisplay(this.inferredGelType);
                gelTypeEl.innerHTML = `
                    <span class="gv-review-gel-badge ${this.inferredGelType.toLowerCase()}">
                        ${gelTypeDisplay}
                    </span>
                `;
            }

            if (countEl) {
                countEl.textContent = `${this.detections.length} lane${this.detections.length !== 1 ? 's' : ''} detected`;
            }
        }

        /**
         * Get display name for gel type.
         */
        _getGelTypeDisplay(gelType) {
            const displays = {
                'SDS_PAGE': 'SDS-PAGE',
                'DOT_BLOT': 'Dot Blot',
                'UNKNOWN': 'Unknown',
            };
            return displays[gelType] || gelType;
        }

        /**
         * Render the detection list.
         */
        _renderDetectionList() {
            if (!this.listContainer) return;

            this.listContainer.innerHTML = '';

            this.detections.forEach((det, index) => {
                const item = this._createDetectionItem(det, index);
                this.listContainer.appendChild(item);
            });

            this._updateAcceptButton();
        }

        /**
         * Create a detection list item.
         */
        _createDetectionItem(detection, index) {
            const item = document.createElement('div');
            item.className = 'gv-review-item selected';
            item.dataset.index = index;

            const isSelected = this.selectedIndices.has(index);
            if (!isSelected) {
                item.classList.remove('selected');
            }

            // Confidence percentage and color
            const confidence = Math.round(detection.confidence * 100);
            const confidenceColor = this._getConfidenceColor(confidence);

            // Class badge color
            const classColor = this._getClassColor(detection.class_name);

            item.innerHTML = `
                <div class="gv-review-item-checkbox">
                    <input type="checkbox" ${isSelected ? 'checked' : ''}>
                </div>
                <div class="gv-review-item-info">
                    <div class="gv-review-item-header">
                        <span class="gv-review-item-number">Lane ${index + 1}</span>
                        <span class="gv-review-class-badge" style="background: ${classColor}">
                            ${this._formatClassName(detection.class_name)}
                        </span>
                    </div>
                    <div class="gv-review-item-meta">
                        <span class="gv-review-lane-type">${detection.lane_type}</span>
                        <span class="gv-review-confidence">
                            <span class="gv-review-confidence-bar" style="width: ${confidence}%; background: ${confidenceColor}"></span>
                            <span class="gv-review-confidence-value">${confidence}%</span>
                        </span>
                    </div>
                </div>
            `;

            // Click handler
            item.addEventListener('click', (e) => {
                if (e.target.type !== 'checkbox') {
                    this.toggleSelection(index);
                }
            });

            // Checkbox change handler
            const checkbox = item.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.addEventListener('change', () => {
                    this.toggleSelection(index);
                });
            }

            // Hover to highlight preview
            item.addEventListener('mouseenter', () => {
                this._highlightPreview(index, true);
            });
            item.addEventListener('mouseleave', () => {
                this._highlightPreview(index, false);
            });

            return item;
        }

        /**
         * Get color based on confidence level.
         */
        _getConfidenceColor(confidence) {
            if (confidence >= 80) return '#14A44D'; // Green
            if (confidence >= 60) return '#E4A11B'; // Yellow
            return '#DC4C64'; // Red
        }

        /**
         * Get color based on class name.
         */
        _getClassColor(className) {
            const colors = {
                'marker_lane': '#f97316', // Orange
                'sample_lane': '#3b82f6', // Blue
                'smear': '#8b5cf6',       // Purple
                'dot_lane': '#22c55e',    // Green
            };
            return colors[className] || '#6b7280';
        }

        /**
         * Format class name for display.
         */
        _formatClassName(className) {
            return className.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
        }

        /**
         * Update selection UI for a specific item.
         */
        _updateSelectionUI(index) {
            const item = this.listContainer?.querySelector(`[data-index="${index}"]`);
            if (!item) return;

            const checkbox = item.querySelector('input[type="checkbox"]');
            const isSelected = this.selectedIndices.has(index);

            if (checkbox) {
                checkbox.checked = isSelected;
            }

            if (isSelected) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }

            // Update preview
            this._updatePreviewSelection(index, isSelected);
        }

        /**
         * Update the accept button text.
         */
        _updateAcceptButton() {
            const btn = document.getElementById('review-accept-selected');
            if (btn) {
                const count = this.selectedIndices.size;
                btn.textContent = `Accept Selected (${count})`;
                btn.disabled = count === 0;
            }
        }

        /**
         * Render detection previews on the SVG.
         */
        _renderPreviews() {
            this._clearPreviews();

            if (!this.previewGroup) return;

            this.detections.forEach((det, index) => {
                this._renderDetectionPreview(det, index);
            });
        }

        /**
         * Render a single detection preview.
         */
        _renderDetectionPreview(detection, index) {
            if (!this.previewGroup) return;

            const polygon = detection.polygon;
            if (!polygon || polygon.length < 3) return;

            // Create polygon element
            const pointsStr = polygon.map(p => p.join(',')).join(' ');
            const isSelected = this.selectedIndices.has(index);

            const poly = this.previewGroup.polygon(pointsStr)
                .attr('id', `detection-preview-${index}`)
                .addClass('gv-detection-preview')
                .addClass(isSelected ? 'selected' : '')
                .attr('data-index', index);

            // Click to toggle selection
            poly.click(() => {
                this.toggleSelection(index);
            });

            // Add confidence badge (as text element positioned at top-left of bbox)
            const [x, y, w, h] = detection.bbox;
            const confidence = Math.round(detection.confidence * 100);

            // Create SVG text element for confidence badge (simpler than foreignObject)
            this.previewGroup.text(`${confidence}%`)
                .attr('x', x + 5)
                .attr('y', y + 15)
                .attr('id', `detection-badge-${index}`)
                .addClass('gv-confidence-text')
                .font({
                    size: 11,
                    weight: 'bold',
                    family: 'sans-serif'
                })
                .fill('#fff')
                .attr('paint-order', 'stroke')
                .attr('stroke', '#000')
                .attr('stroke-width', 3);
        }

        /**
         * Update preview selection state.
         */
        _updatePreviewSelection(index, isSelected) {
            if (!this.previewGroup) return;

            const preview = this.previewGroup.findOne(`#detection-preview-${index}`);
            if (preview) {
                if (isSelected) {
                    preview.addClass('selected');
                } else {
                    preview.removeClass('selected');
                }
            }
        }

        /**
         * Highlight a preview on hover.
         */
        _highlightPreview(index, highlight) {
            if (!this.previewGroup) return;

            const preview = this.previewGroup.findOne(`#detection-preview-${index}`);
            if (preview) {
                if (highlight) {
                    preview.addClass('highlighted');
                } else {
                    preview.removeClass('highlighted');
                }
            }
        }

        /**
         * Clear all previews.
         */
        _clearPreviews() {
            if (this.previewGroup) {
                this.previewGroup.clear();
            }
        }

        /**
         * Show a message to the user.
         */
        _showMessage(text) {
            // Use the existing message system from GelViewer
            const existing = document.querySelector('.gv-message');
            if (existing) existing.remove();

            const message = document.createElement('div');
            message.className = 'gv-message';
            message.textContent = text;

            const viewer = document.querySelector('.gv-viewer');
            if (viewer) {
                viewer.appendChild(message);
                setTimeout(() => message.remove(), 2000);
            }
        }

        /**
         * Check if panel is currently visible.
         * @returns {boolean}
         */
        isOpen() {
            return this.isVisible;
        }

        /**
         * Get selected detections.
         * @returns {Array<Object>}
         */
        getSelectedDetections() {
            return this.detections.filter((_, i) => this.selectedIndices.has(i));
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ReviewPanel = ReviewPanel;

})(window);
