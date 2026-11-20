/**
 * ToolManager - Tool Switching and Management for GelViewer
 *
 * Manages the current active tool and coordinates between
 * different drawing modes (select, pan, lane, band, split).
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * ToolManager Class
     * Manages tool state and switching.
     */
    class ToolManager {
        /**
         * Create a ToolManager instance.
         * @param {Object} options - Configuration options
         * @param {HTMLElement} options.viewer - The viewer element
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {boolean} options.isEditable - Whether annotations can be edited
         * @param {Function} options.showMessage - Function to display messages
         * @param {Function} options.cancelDrawing - Function to cancel any drawing in progress
         * @param {Function} options.deselect - Function to deselect current selection
         */
        constructor(options) {
            this.viewer = options.viewer;
            this.eventBus = options.eventBus;
            this.isEditable = options.isEditable !== false;
            this.showMessage = options.showMessage || console.log;
            this.cancelDrawing = options.cancelDrawing || (() => {});
            this.deselect = options.deselect || (() => {});

            // State
            this.currentTool = 'select';
            this.laneShape = 'RECTANGLE';

            // Tool instances (set externally)
            this.tools = {
                select: null,
                pan: null,
                lane: null,
                band: null,
                split: null
            };

            this._setupToolbarEvents();
            this._setupLaneShapeDropdown();
        }

        /**
         * Setup toolbar button click events.
         */
        _setupToolbarEvents() {
            document.querySelectorAll('.gv-toolbar-btn[data-tool]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const tool = btn.dataset.tool;
                    if (tool && tool !== 'lane') {
                        this.setTool(tool);
                    }
                });
            });
        }

        /**
         * Setup lane shape dropdown.
         */
        _setupLaneShapeDropdown() {
            const dropdown = document.querySelector('.gv-tool-dropdown');
            const trigger = dropdown?.querySelector('.gv-dropdown-trigger');
            const menu = document.getElementById('lane-shape-menu');

            if (trigger) {
                trigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (this.currentTool === 'lane') {
                        this.toggleLaneDropdown();
                    } else {
                        this.setTool('lane');
                    }
                });
            }

            if (menu) {
                menu.querySelectorAll('.gv-dropdown-item').forEach(item => {
                    item.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const shape = item.dataset.laneShape;
                        if (shape) {
                            this.setLaneShape(shape);
                        }
                    });
                });
            }

            // Close dropdown on outside click
            document.addEventListener('click', () => {
                if (dropdown) dropdown.classList.remove('open');
            });
        }

        // =====================================================================
        // Tool Switching
        // =====================================================================

        /**
         * Set the current tool.
         * @param {string} toolName - Tool name: 'select', 'pan', 'lane', 'band', 'split'
         */
        setTool(toolName) {
            const previousTool = this.currentTool;
            this.currentTool = toolName;

            // Update viewer cursor class (remove old tool class, add new one)
            if (this.viewer) {
                // Remove previous tool class
                this.viewer.classList.remove('tool-select', 'tool-pan', 'tool-lane', 'tool-band', 'tool-split', 'tool-crop');
                // Add new tool class
                this.viewer.classList.add('tool-' + toolName);
            }

            // Cancel any drawing in progress
            this.cancelDrawing();

            // Deselect when switching to drawing tools (except split which needs selection)
            if (toolName === 'lane' || toolName === 'band') {
                this.deselect();
            }

            // Update toolbar buttons
            document.querySelectorAll('.gv-toolbar-btn[data-tool]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tool === toolName);
            });

            // Close lane shape dropdown when switching tools
            const laneDropdown = document.querySelector('.gv-tool-dropdown');
            if (laneDropdown && toolName !== 'lane') {
                laneDropdown.classList.remove('open');
            }

            this.showMessage(`Tool: ${toolName.charAt(0).toUpperCase() + toolName.slice(1)}`);

            this.eventBus.emit(Events.TOOL_CHANGED, {
                tool: toolName,
                previousTool
            });
        }

        /**
         * Get the current tool name.
         * @returns {string}
         */
        getTool() {
            return this.currentTool;
        }

        /**
         * Check if the current tool is a drawing tool.
         * @returns {boolean}
         */
        isDrawingTool() {
            return ['lane', 'band', 'split'].includes(this.currentTool);
        }

        // =====================================================================
        // Lane Shape
        // =====================================================================

        /**
         * Set the lane shape for the lane tool.
         * @param {string} shape - Shape name: 'RECTANGLE', 'QUADRILATERAL', 'POLYGON'
         */
        setLaneShape(shape) {
            this.laneShape = shape;

            // Update dropdown UI
            const menu = document.getElementById('lane-shape-menu');
            if (menu) {
                menu.querySelectorAll('.gv-dropdown-item').forEach(item => {
                    item.classList.toggle('active', item.dataset.laneShape === shape);
                });
            }

            // Update icon based on shape
            const icon = document.getElementById('lane-tool-icon');
            if (icon) {
                icon.className = 'bi';
                switch (shape) {
                    case 'RECTANGLE':
                        icon.classList.add('bi-square');
                        break;
                    case 'QUADRILATERAL':
                        icon.classList.add('bi-diamond');
                        break;
                    case 'POLYGON':
                        icon.classList.add('bi-hexagon');
                        break;
                }
            }

            // Switch to lane tool
            this.setTool('lane');

            // Close dropdown
            const dropdown = document.querySelector('.gv-tool-dropdown');
            if (dropdown) {
                dropdown.classList.remove('open');
            }

            this.showMessage(`Lane Tool: ${shape.charAt(0) + shape.slice(1).toLowerCase()}`);

            this.eventBus.emit(Events.LANE_SHAPE_CHANGED, { shape });
        }

        /**
         * Get the current lane shape.
         * @returns {string}
         */
        getLaneShape() {
            return this.laneShape;
        }

        /**
         * Toggle lane shape dropdown.
         */
        toggleLaneDropdown() {
            const dropdown = document.querySelector('.gv-tool-dropdown');
            if (dropdown) {
                dropdown.classList.toggle('open');
                if (dropdown.classList.contains('open')) {
                    // Esc closes the menu alone. Closed by a click, a shape or a tool change: isOpen drops it.
                    global.GelViewer.Layers?.open(dropdown, {
                        close: () => dropdown.classList.remove('open'),
                        isOpen: () => dropdown.classList.contains('open'),
                    });
                } else {
                    global.GelViewer.Layers?.close(dropdown);
                }
            }
        }

        // =====================================================================
        // Tool Registration
        // =====================================================================

        /**
         * Register a tool instance.
         * @param {string} name - Tool name
         * @param {Object} tool - Tool instance
         */
        registerTool(name, tool) {
            this.tools[name] = tool;
        }

        /**
         * Get a registered tool instance.
         * @param {string} name - Tool name
         * @returns {Object|null}
         */
        getToolInstance(name) {
            return this.tools[name] || null;
        }

        /**
         * Get the active tool instance.
         * @returns {Object|null}
         */
        getActiveTool() {
            return this.tools[this.currentTool] || null;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ToolManager = ToolManager;

})(window);
