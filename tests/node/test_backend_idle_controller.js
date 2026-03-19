const assert = require('assert');
const { BackendIdleController } = require('../../src/main/backend-idle-controller');

class FakeClock {
    constructor() {
        this.now = 0;
        this._nextId = 1;
        this._timers = new Map();
    }

    setTimeout(fn, delay) {
        const id = this._nextId++;
        this._timers.set(id, {
            id,
            dueAt: this.now + Math.max(0, Number(delay || 0)),
            fn,
        });
        return id;
    }

    clearTimeout(id) {
        this._timers.delete(id);
    }

    advance(ms) {
        const target = this.now + Math.max(0, Number(ms || 0));
        while (true) {
            const nextTimer = [...this._timers.values()]
                .sort((left, right) => left.dueAt - right.dueAt)[0];
            if (!nextTimer || nextTimer.dueAt > target) {
                break;
            }
            this.now = nextTimer.dueAt;
            this._timers.delete(nextTimer.id);
            nextTimer.fn();
        }
        this.now = target;
    }
}

function createController(clock, options = {}) {
    const stopReasons = [];
    const states = [];
    const controller = new BackendIdleController({
        delayMs: 15 * 60 * 1000,
        now: () => clock.now,
        setTimer: (fn, delay) => clock.setTimeout(fn, delay),
        clearTimer: (id) => clock.clearTimeout(id),
        onStopService: async (reason) => {
            stopReasons.push(reason);
            controller.setServiceStopped(reason);
        },
        onStateChange: (state) => {
            states.push({ ...state });
        },
        ...options,
    });
    return { controller, stopReasons, states };
}

async function run() {
    const clock = new FakeClock();
    const { controller, stopReasons } = createController(clock);

    controller.setServiceRunning(true);
    assert.equal(controller.getState().state, 'standby');

    controller.setWindowVisible(false);
    assert.equal(controller.getState().state, 'countdown');
    assert.equal(controller.getState().remainingMs, 15 * 60 * 1000);

    clock.advance(5 * 60 * 1000);
    assert.equal(controller.getState().remainingMs, 10 * 60 * 1000);

    controller.setWindowVisible(true);
    assert.equal(controller.getState().state, 'standby');
    assert.equal(controller.getState().remainingMs, 10 * 60 * 1000);

    controller.cancelIdleShutdown();
    assert.equal(controller.getState().state, 'standby');
    assert.equal(controller.getState().remainingMs, 15 * 60 * 1000);

    controller.setWindowVisible(false);
    assert.equal(controller.getState().state, 'countdown');

    clock.advance(15 * 60 * 1000);
    await Promise.resolve();
    assert.equal(controller.getState().state, 'stopped_by_idle');
    assert.deepEqual(stopReasons, ['idle_timeout']);

    controller.setServiceRunning(true);
    controller.setWindowVisible(false);
    assert.equal(controller.getState().state, 'countdown');

    controller.updateRuntime({ botRunning: true, growthRunning: false });
    assert.equal(controller.getState().state, 'active');

    controller.updateRuntime({ botRunning: false, growthRunning: false });
    assert.equal(controller.getState().state, 'countdown');

    controller.setWindowVisible(true);
    assert.equal(controller.getState().state, 'standby');
}

run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
