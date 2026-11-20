/**
 * ConfirmationManager - Vanilla JS confirmation dialogs for gel-viewer
 *
 * Provides a Promise-based API for showing confirmation dialogs
 * before destructive actions. Uses CSS classes from gel_viewer.css
 * (#gv-confirm-modal) — no MDB5 dependency. prompt() asks for one value
 * on the window kit: the editor never calls the browser's confirm / alert / prompt.
 */

(function(global) {
    'use strict';

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    class ConfirmationManager {
        constructor() {
            this.modal = null;
            this.resolvePromise = null;
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

            // Esc: GelViewer.Layers (show) calls _resolve(false) - never a click on Cancel, which the backup
            // restore reads as Discard (GelViewerApp._offerBackup).
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
            if (global.GelViewer && global.GelViewer.Layers) global.GelViewer.Layers.close(this.modal);
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

                // A dialog shown over one still open: the first one is answered "cancel", never left pending. A value
                // window too: drawn above this one (z 11000), it would hide the dialog that now takes Esc and the keys.
                if (this.resolvePromise) this._resolve(false);
                if (this._cancelPrompt) this._cancelPrompt();
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

                // Show. The focus goes to Cancel on a destructive confirm; on the others (the backup restore, where
                // Cancel is Discard) to the dialog box, so Enter or Space decides nothing by accident.
                this.modal.classList.add('show');
                this.modal.removeAttribute('aria-hidden');
                if (global.GelViewer && global.GelViewer.Layers) {
                    global.GelViewer.Layers.open(this.modal, {
                        modal: true,
                        close: () => this._resolve(false),
                        isOpen: () => this.modal.classList.contains('show'),
                        initialFocus: options.danger !== false ? cancelBtn : this.modal.querySelector('.modal-content'),
                    });
                }
            });
        }

        /**
         * Ask for one value - the editor's window.prompt, on the window kit (night and day, a phone). It answers what
         * window.prompt answered: the text as typed (the caller parses it, as before), or null when cancelled - Cancel,
         * the close button, a click beside it, Esc (GelViewer.Layers: Esc never decides). Enter in the field is OK.
         *
         * @param {Object} options
         * @param {string} options.title - Window title
         * @param {string} options.label - The field's label
         * @param {string|number} [options.value=''] - Pre-filled and selected
         * @param {string} [options.hint] - A line under the field
         * @param {string} [options.inputMode='text'] - 'decimal' gives a phone its number pad (the field stays text:
         *        a number field would answer '' for "12,5" where window.prompt answered "12,5")
         * @param {string} [options.confirmText='OK'] - OK button text
         * @param {string} [options.icon='input-cursor-text'] - Bootstrap icon
         * @returns {Promise<string|null>}
         */
        prompt(options = {}) {
            return new Promise((resolve) => {
                // One at a time, as show(): one still open is answered "cancel", never left pending.
                if (this._cancelPrompt) this._cancelPrompt();

                const layer = document.createElement('div');
                layer.className = 'gv-win-layer';
                layer.innerHTML = `
                    <div class="gv-win-backdrop"></div>
                    <div class="gv-win" role="dialog" aria-modal="true" aria-labelledby="gv-prompt-title">
                        <header class="gv-win-head">
                            <h3 class="gv-win-title" id="gv-prompt-title"><i class="bi"></i><span></span></h3>
                            <button type="button" class="gv-win-close" aria-label="Close"><i class="bi bi-x-lg"></i></button>
                        </header>
                        <div class="gv-win-body">
                            <label class="gv-win-label" for="gv-prompt-input"></label>
                            <input type="text" class="gv-win-input" id="gv-prompt-input" autocomplete="off" spellcheck="false">
                            <div class="gv-win-hint gv-prompt-hint"></div>
                        </div>
                        <footer class="gv-win-foot">
                            <button type="button" class="gv-win-btn" data-prompt="cancel">Cancel</button>
                            <button type="button" class="gv-win-btn gv-win-btn--primary" data-prompt="ok"></button>
                        </footer>
                    </div>
                `;

                // Text only: a title or a value may carry a band's own label.
                layer.querySelector('.gv-win-title i').className = 'bi bi-' + (options.icon || 'input-cursor-text');
                layer.querySelector('.gv-win-title span').textContent = options.title || 'Enter a value';
                layer.querySelector('.gv-win-label').textContent = options.label || '';
                layer.querySelector('.gv-prompt-hint').textContent = options.hint || '';
                layer.querySelector('[data-prompt="ok"]').textContent = options.confirmText || 'OK';
                const input = layer.querySelector('.gv-win-input');
                input.value = options.value == null ? '' : String(options.value);
                input.inputMode = options.inputMode || 'text';

                const finish = (answer) => {
                    this._cancelPrompt = null;
                    if (global.GelViewer && global.GelViewer.Layers) global.GelViewer.Layers.close(layer);
                    layer.remove();
                    resolve(answer);
                };
                const cancel = () => finish(null);
                this._cancelPrompt = cancel;

                layer.querySelector('.gv-win-backdrop').addEventListener('click', cancel);
                layer.querySelector('.gv-win-close').addEventListener('click', cancel);
                layer.querySelector('[data-prompt="cancel"]').addEventListener('click', cancel);
                layer.querySelector('[data-prompt="ok"]').addEventListener('click', () => finish(input.value));
                // Enter answers from the field only: on Cancel or the close button it presses them.
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.isComposing) {
                        e.preventDefault();
                        finish(input.value);
                    }
                });

                document.body.appendChild(layer);
                if (global.GelViewer && global.GelViewer.Layers) {
                    global.GelViewer.Layers.open(layer, {
                        modal: true,
                        close: cancel,
                        isOpen: () => layer.isConnected,
                        initialFocus: input,
                    });
                } else {
                    input.focus();
                }
                // Selected once the focus has landed (Layers moves it after layout), as window.prompt selects its value.
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    if (document.activeElement === input) input.select();
                }));
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

        // The label is the user's own text (or "Band N"): escaped, the body is HTML.
        confirmDeleteBand(label, laneNumber = null) {
            const where = laneNumber != null ? ` in <strong>Lane ${escapeHtml(laneNumber)}</strong>` : '';

            return this.show({
                title: 'Delete Band',
                body: `
                    <p>Delete <strong>${escapeHtml(label)}</strong>${where} permanently?</p>
                    <p class="text-muted">
                        <i class="bi bi-exclamation-circle me-1"></i>
                        This action cannot be undone.
                    </p>
                `,
                confirmText: 'Delete Band',
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
