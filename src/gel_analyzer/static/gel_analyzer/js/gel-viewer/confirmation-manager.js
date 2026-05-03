/**
 * ConfirmationManager - Vanilla JS confirmation dialogs for gel-viewer
 *
 * Provides a Promise-based API for showing confirmation dialogs
 * before destructive actions. Uses CSS classes from gel_viewer.css
 * (#gv-confirm-modal) — no MDB5 dependency.
 */

(function(global) {
    'use strict';

    class ConfirmationManager {
        constructor() {
            this.modal = null;
            this.resolvePromise = null;
            this._escHandler = null;
            this._setup();
        }

        _setup() {
            this.modal = document.getElementById('gv-confirm-modal');
            if (!this.modal) {
                console.warn('ConfirmationManager: #gv-confirm-modal not found');
                return;
            }

            // Confirm button
            const confirmBtn = document.getElementById('gv-confirm-action');
            if (confirmBtn) {
                confirmBtn.addEventListener('click', () => this._resolve(true));
            }

            // Cancel button
            const cancelBtn = document.getElementById('gv-confirm-cancel');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this._resolve(false));
            }

            // Backdrop click to close
            const backdrop = this.modal.querySelector('.gv-confirm-backdrop');
            if (backdrop) {
                backdrop.addEventListener('click', () => {
                    if (this.resolvePromise) this._resolve(false);
                });
            }

            // ESC key handler (attached only while open)
            this._escHandler = (e) => {
                if (e.key === 'Escape' && this.resolvePromise) {
                    e.stopPropagation();
                    this._resolve(false);
                }
            };
        }

        _resolve(result) {
            if (this.resolvePromise) {
                const resolve = this.resolvePromise;
                this.resolvePromise = null;
                this._hide();
                resolve(result);
            }
        }

        _hide() {
            if (!this.modal) return;
            this.modal.classList.remove('show');
            this.modal.setAttribute('aria-hidden', 'true');
            document.removeEventListener('keydown', this._escHandler);
        }

        /**
         * Show a confirmation dialog.
         *
         * @param {Object} options
         * @param {string} options.title - Modal title
         * @param {string} options.body - Modal body content (HTML)
         * @param {string} [options.confirmText='Confirm'] - Confirm button text
         * @param {string} [options.cancelText='Cancel'] - Cancel button text
         * @param {boolean} [options.danger=true] - Danger (red) styling
         * @param {string} [options.icon='exclamation-triangle-fill'] - Bootstrap icon
         * @returns {Promise<boolean>}
         */
        show(options) {
            return new Promise((resolve) => {
                if (!this.modal) {
                    console.warn('ConfirmationManager: no modal, auto-confirming');
                    resolve(true);
                    return;
                }

                this.resolvePromise = resolve;

                // Update content
                const titleEl = document.getElementById('gv-confirm-title');
                const bodyEl = document.getElementById('gv-confirm-body');
                const confirmBtn = document.getElementById('gv-confirm-action');
                const cancelBtn = document.getElementById('gv-confirm-cancel');
                const headerEl = this.modal.querySelector('.modal-header');
                const iconEl = this.modal.querySelector('.modal-title i');

                if (titleEl) titleEl.textContent = options.title || 'Confirmation';
                if (bodyEl) bodyEl.innerHTML = options.body || 'Are you sure?';

                if (confirmBtn) {
                    confirmBtn.textContent = options.confirmText || 'Confirm';
                    confirmBtn.className = options.danger !== false
                        ? 'btn btn-danger' : 'btn btn-primary';
                }

                if (cancelBtn) {
                    cancelBtn.textContent = options.cancelText || 'Cancel';
                }

                if (headerEl) {
                    headerEl.className = 'modal-header ' +
                        (options.danger !== false ? 'bg-warning' : 'bg-primary');
                }

                if (iconEl) {
                    iconEl.className = 'bi bi-' +
                        (options.icon || 'exclamation-triangle-fill') + ' me-2';
                }

                // Show
                this.modal.classList.add('show');
                this.modal.removeAttribute('aria-hidden');
                document.addEventListener('keydown', this._escHandler);
            });
        }

        // =================================================================
        // Preset Confirmation Dialogs
        // =================================================================

        confirmDetectLanes(existingCount, bandCount = 0) {
            const bandWarning = bandCount > 0
                ? `<p class="text-danger"><i class="bi bi-exclamation-diamond-fill me-1"></i><strong>${bandCount} band${bandCount > 1 ? 's' : ''}</strong> will also be deleted.</p>`
                : '';

            return this.show({
                title: 'Replace Existing Lanes',
                body: `
                    <p>You have <strong>${existingCount} existing lane${existingCount > 1 ? 's' : ''}</strong> that will be replaced.</p>
                    ${bandWarning}
                    <p class="text-muted">
                        <i class="bi bi-arrow-repeat me-1"></i>
                        New lanes will be detected using YOLO AI.
                    </p>
                `,
                confirmText: 'Replace & Detect',
                cancelText: 'Keep Current',
                danger: true,
                icon: 'arrow-repeat',
            });
        }

        confirmDetectBands(existingCount, laneCount) {
            return this.show({
                title: 'Detect Bands',
                body: `
                    <p><strong>${existingCount} existing band${existingCount > 1 ? 's' : ''}</strong>
                    in <strong>${laneCount} lane${laneCount > 1 ? 's' : ''}</strong> will be replaced.</p>
                    <p class="text-muted">
                        <i class="bi bi-info-circle me-1"></i>
                        Manually created bands will be preserved.
                    </p>
                `,
                confirmText: 'Replace & Detect',
                cancelText: 'Keep Current',
                danger: true,
                icon: 'layers-fill',
            });
        }

        confirmRemoveAllLanes(laneCount, bandCount) {
            const bandWarning = bandCount > 0
                ? `<p class="text-danger"><i class="bi bi-exclamation-diamond-fill me-1"></i><strong>${bandCount} band${bandCount > 1 ? 's' : ''}</strong> will also be deleted.</p>`
                : '';

            return this.show({
                title: 'Delete All Lanes',
                body: `
                    <p>Delete <strong>${laneCount} lane${laneCount > 1 ? 's' : ''}</strong> permanently?</p>
                    ${bandWarning}
                    <p class="text-muted">
                        <i class="bi bi-exclamation-circle me-1"></i>
                        This action cannot be undone.
                    </p>
                `,
                confirmText: 'Delete All',
                cancelText: 'Cancel',
                danger: true,
                icon: 'trash3-fill',
            });
        }

        confirmRemoveAllBands(bandCount) {
            return this.show({
                title: 'Delete All Bands',
                body: `
                    <p>Delete <strong>${bandCount} band${bandCount > 1 ? 's' : ''}</strong> permanently?</p>
                    <p class="text-muted">
                        <i class="bi bi-exclamation-circle me-1"></i>
                        This action cannot be undone.
                    </p>
                `,
                confirmText: 'Delete All',
                cancelText: 'Cancel',
                danger: true,
                icon: 'trash3-fill',
            });
        }

        confirmRecalibration() {
            return this.show({
                title: 'Update Calibration',
                body: `
                    <p>The existing MW calibration will be <strong>replaced</strong> with new values.</p>
                    <p class="text-muted">
                        <i class="bi bi-graph-up me-1"></i>
                        Band MW values will be recalculated.
                    </p>
                `,
                confirmText: 'Recalibrate',
                cancelText: 'Keep Current',
                danger: false,
                icon: 'rulers',
            });
        }

        confirmCrop(width, height) {
            return this.show({
                title: 'Crop Image',
                body: `
                    <p>Crop image to selected region (<strong>${width} x ${height}</strong> pixels)?</p>
                    <p class="text-muted">
                        <i class="bi bi-exclamation-circle me-1"></i>
                        This cannot be undone. The original image will be replaced.
                    </p>
                `,
                confirmText: 'Crop',
                cancelText: 'Cancel',
                danger: false,
                icon: 'crop',
            });
        }

        confirmDeleteLane(laneNumber, bandCount = 0) {
            const bandWarning = bandCount > 0
                ? `<p class="text-danger"><i class="bi bi-exclamation-diamond-fill me-1"></i><strong>${bandCount} band${bandCount > 1 ? 's' : ''}</strong> will also be deleted.</p>`
                : '';

            return this.show({
                title: 'Delete Lane',
                body: `
                    <p>Delete <strong>Lane ${laneNumber}</strong> permanently?</p>
                    ${bandWarning}
                    <p class="text-muted">
                        <i class="bi bi-exclamation-circle me-1"></i>
                        This action cannot be undone.
                    </p>
                `,
                confirmText: 'Delete Lane',
                cancelText: 'Cancel',
                danger: true,
                icon: 'trash3-fill',
            });
        }
    }

    // Export
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ConfirmationManager = ConfirmationManager;

})(window);
