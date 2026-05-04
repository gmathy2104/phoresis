/**
 * DragReorder - Lightweight HTML5 Drag and Drop reorder utility.
 *
 * Provides drag-and-drop reordering for flex container children.
 * Auto-detects horizontal vs vertical layout from flex-direction.
 *
 * Usage:
 *   const reorder = new DragReorder({
 *       container: element,
 *       itemSelector: '.dm-sample-card',
 *       dataKey: 'sampleId',
 *       onReorder: (orderedIds) => state.reorderSamples(orderedIds)
 *   });
 *   // After each render (innerHTML recreates DOM):
 *   reorder.attach();
 */

(function(global) {
    'use strict';

    class DragReorder {
        constructor(options) {
            this.container = options.container;
            this.itemSelector = options.itemSelector;
            this.handleSelector = options.handleSelector || null;
            this.dataKey = options.dataKey;
            this.onReorder = options.onReorder;

            this._draggedEl = null;

            // Bind for consistent references
            this._onDragStart = this._onDragStart.bind(this);
            this._onDragOver = this._onDragOver.bind(this);
            this._onDragEnd = this._onDragEnd.bind(this);
            this._onDrop = this._onDrop.bind(this);
        }

        /**
         * Attach drag listeners to current items.
         * Call after each render since innerHTML recreates DOM.
         */
        attach() {
            if (!this.container) return;

            const items = this.container.querySelectorAll(this.itemSelector);
            items.forEach(item => {
                item.setAttribute('draggable', 'true');
                item.addEventListener('dragstart', this._onDragStart);
                item.addEventListener('dragover', this._onDragOver);
                item.addEventListener('dragend', this._onDragEnd);
                item.addEventListener('drop', this._onDrop);
            });
        }

        _onDragStart(e) {
            // If handleSelector specified, only allow drag from handle
            if (this.handleSelector && !e.target.closest(this.handleSelector)) {
                e.preventDefault();
                return;
            }

            this._draggedEl = e.currentTarget;
            this._draggedEl.classList.add('dm-dragging');

            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', this._draggedEl.dataset[this.dataKey]);

            // Delay opacity change to allow browser ghost image to render
            requestAnimationFrame(() => {
                if (this._draggedEl) {
                    this._draggedEl.style.opacity = '0.4';
                }
            });
        }

        _onDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            const targetItem = e.currentTarget;
            if (targetItem === this._draggedEl || !this._draggedEl) return;

            // Determine insertion based on mouse position relative to target center
            const rect = targetItem.getBoundingClientRect();
            const isHorizontal = this._isHorizontalLayout();

            const midpoint = isHorizontal
                ? rect.left + rect.width / 2
                : rect.top + rect.height / 2;

            const mousePos = isHorizontal ? e.clientX : e.clientY;
            const parent = targetItem.parentNode;

            if (mousePos < midpoint) {
                parent.insertBefore(this._draggedEl, targetItem);
            } else {
                parent.insertBefore(this._draggedEl, targetItem.nextSibling);
            }
        }

        _onDrop(e) {
            e.preventDefault();
        }

        _onDragEnd() {
            if (this._draggedEl) {
                this._draggedEl.classList.remove('dm-dragging');
                this._draggedEl.style.opacity = '';
            }

            // Read new order from DOM
            if (this.container) {
                const items = this.container.querySelectorAll(this.itemSelector);
                const newOrder = Array.from(items).map(item => item.dataset[this.dataKey]);

                this._draggedEl = null;

                if (this.onReorder) {
                    this.onReorder(newOrder);
                }
            } else {
                this._draggedEl = null;
            }
        }

        _isHorizontalLayout() {
            if (!this.container) return true;
            const style = window.getComputedStyle(this.container);
            const dir = style.flexDirection;
            return dir === 'row' || dir === 'row-reverse';
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.DragReorder = DragReorder;

})(window);
