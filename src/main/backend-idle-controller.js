const DEFAULT_IDLE_SHUTDOWN_MS = 15 * 60 * 1000;

function clampRemainingMs(value, fallback) {
    const next = Number(value);
    if (!Number.isFinite(next)) {
        return fallback;
    }
    return Math.max(0, Math.floor(next));
}

class BackendIdleController {
    constructor(options = {}) {
        this.delayMs = clampRemainingMs(
            options.delayMs,
            DEFAULT_IDLE_SHUTDOWN_MS,
        ) || DEFAULT_IDLE_SHUTDOWN_MS;
        this._now = typeof options.now === 'function' ? options.now : () => Date.now();
        this._setTimer = typeof options.setTimer === 'function' ? options.setTimer : setTimeout;
        this._clearTimer = typeof options.clearTimer === 'function' ? options.clearTimer : clearTimeout;
        this._onStopService = typeof options.onStopService === 'function'
            ? options.onStopService
            : async () => {};
        this._onStateChange = typeof options.onStateChange === 'function'
            ? options.onStateChange
            : () => {};

        this._serviceRunning = false;
        this._windowVisible = true;
        this._runtime = {
            botRunning: false,
            growthRunning: false,
        };
        this._state = 'active';
        this._reason = '';
        this._remainingMs = this.delayMs;
        this._updatedAt = this._now();
        this._timer = null;
        this._timerToken = 0;
    }

    getState() {
        return {
            state: this._state,
            delayMs: this.delayMs,
            remainingMs: this._state === 'countdown'
                ? this._getLiveRemainingMs()
                : this._remainingMs,
            reason: this._reason,
            updatedAt: this._updatedAt,
        };
    }

    setWindowVisible(visible) {
        const next = !!visible;
        if (this._windowVisible === next) {
            return this.getState();
        }
        this._windowVisible = next;
        this._reconcileState();
        return this.getState();
    }

    setServiceRunning(running) {
        const next = !!running;
        if (this._serviceRunning === next) {
            this._reconcileState();
            return this.getState();
        }
        this._serviceRunning = next;
        if (next) {
            this._reason = '';
            this._remainingMs = this.delayMs;
            this._updatedAt = this._now();
        } else {
            this._cancelTimer();
        }
        this._reconcileState();
        return this.getState();
    }

    setServiceStopped(reason = '') {
        this._serviceRunning = false;
        this._cancelTimer();
        this._remainingMs = this.delayMs;
        this._updatedAt = this._now();
        if (reason === 'idle_timeout') {
            this._transitionTo('stopped_by_idle', 0, 'idle_timeout');
            return this.getState();
        }
        this._transitionTo('active', this.delayMs, '');
        return this.getState();
    }

    updateRuntime(summary = {}) {
        const nextBotRunning = !!summary.botRunning;
        const nextGrowthRunning = !!summary.growthRunning;
        if (
            this._runtime.botRunning === nextBotRunning
            && this._runtime.growthRunning === nextGrowthRunning
        ) {
            this._reconcileState();
            return this.getState();
        }
        this._runtime = {
            botRunning: nextBotRunning,
            growthRunning: nextGrowthRunning,
        };
        this._reconcileState();
        return this.getState();
    }

    cancelIdleShutdown() {
        if (!this._serviceRunning || this._hasRuntimeActivity()) {
            return this.getState();
        }
        this._reason = '';
        this._remainingMs = this.delayMs;
        this._updatedAt = this._now();
        this._reconcileState();
        return this.getState();
    }

    dispose() {
        this._cancelTimer();
    }

    _hasRuntimeActivity() {
        return this._runtime.botRunning || this._runtime.growthRunning;
    }

    _getLiveRemainingMs() {
        const elapsed = Math.max(0, this._now() - this._updatedAt);
        return Math.max(0, this._remainingMs - elapsed);
    }

    _cancelTimer() {
        if (this._timer) {
            this._clearTimer(this._timer);
            this._timer = null;
        }
        this._timerToken += 1;
    }

    _transitionTo(state, remainingMs, reason = '') {
        const nextRemainingMs = clampRemainingMs(
            remainingMs,
            state === 'stopped_by_idle' ? 0 : this.delayMs,
        );
        const nextUpdatedAt = this._now();
        if (
            this._state === state
            && this._reason === reason
            && this._remainingMs === nextRemainingMs
        ) {
            this._updatedAt = nextUpdatedAt;
            return;
        }
        this._state = state;
        this._reason = reason;
        this._remainingMs = nextRemainingMs;
        this._updatedAt = nextUpdatedAt;
        this._onStateChange(this.getState());
    }

    _reconcileState() {
        if (!this._serviceRunning) {
            if (this._state !== 'stopped_by_idle') {
                this._transitionTo('active', this.delayMs, '');
            }
            return;
        }

        if (this._hasRuntimeActivity()) {
            this._cancelTimer();
            this._transitionTo('active', this.delayMs, '');
            return;
        }

        if (this._windowVisible) {
            const remainingMs = this._state === 'countdown'
                ? this._getLiveRemainingMs()
                : this._remainingMs;
            this._cancelTimer();
            this._transitionTo('standby', remainingMs || this.delayMs, '');
            return;
        }

        const remainingMs = this._state === 'countdown'
            ? this._getLiveRemainingMs()
            : this._remainingMs;
        this._startCountdown(remainingMs || this.delayMs);
    }

    _startCountdown(remainingMs) {
        const nextRemainingMs = clampRemainingMs(remainingMs, this.delayMs);
        this._cancelTimer();
        this._transitionTo('countdown', nextRemainingMs, '');
        if (nextRemainingMs <= 0) {
            void this._handleCountdownComplete();
            return;
        }

        const token = this._timerToken;
        this._timer = this._setTimer(() => {
            if (token !== this._timerToken) {
                return;
            }
            this._timer = null;
            void this._handleCountdownComplete();
        }, nextRemainingMs);
    }

    async _handleCountdownComplete() {
        if (!this._serviceRunning || this._hasRuntimeActivity()) {
            this._reconcileState();
            return;
        }
        this._cancelTimer();
        this._transitionTo('stopped_by_idle', 0, 'idle_timeout');
        try {
            await this._onStopService('idle_timeout');
        } catch (error) {
            if (this._serviceRunning) {
                this._remainingMs = this.delayMs;
                this._updatedAt = this._now();
                this._reconcileState();
            }
            throw error;
        }
    }
}

module.exports = {
    BackendIdleController,
    DEFAULT_IDLE_SHUTDOWN_MS,
};
