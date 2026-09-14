import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import vm from "node:vm";
import test from "node:test";

test("bot controls use saved IDs, preserve drafts, reject scoped actions and stop on cleanup", async () => {
    const calls = [];
    const timers = new Set();
    let pendingStatus;
    const runtime = [
        { id: "first", name: "Server label", enabled: true, configured: true, running: true, status: "connected" },
        { id: "second", enabled: true, configured: true, running: false, status: "stopped" },
    ];
    const sandbox = {
        crypto: { randomUUID },
        createStore: (_name, value) => value,
        notifications: { createNotification: () => {} },
        setInterval: fn => { timers.add(fn); return fn; },
        clearInterval: fn => timers.delete(fn),
        callJsonApi: async (url, input) => {
            calls.push({ url, ...input });
            if (url === "agents") return { data: [] };
            if (input.action === "status") return pendingStatus || { ok: true, bots: runtime };
            if (["approve", "revoke"].includes(input.action)) return { ok: true, access: [] };
            return { ok: true, running: input.action !== "stop", status: input.action === "stop" ? "stopped" : "connecting" };
        },
    };
    const source = readFileSync(new URL("../webui/discord-store.js", import.meta.url), "utf8")
        .replace(/^import .*;\n/gm, "")
        .replace("export const store =", "globalThis.store =");
    vm.runInNewContext(source, sandbox);
    const store = sandbox.store;
    const config = { bots: [
        { id: "first", name: "First", token: "secret-one" },
        { id: "second", name: "Second", token: "secret-two" },
    ] };
    const context = { projectName: "", agentProfileKey: "" };
    await store.initConfig(config, context);
    const [first, second] = config.bots;
    assert.equal(timers.size, 1);
    assert.equal(store.statusLabel(first), "Connected");
    assert.deepEqual(Array.from(store.controlsFor(first), control => control.action), ["stop", "restart"]);
    assert.deepEqual(Array.from(store.controlsFor(second), control => control.action), ["start", "restart"]);

    const before = JSON.stringify(config);
    await store.action(first, "stop");
    assert.equal(store.controlsFor(first)[0].icon, "play_arrow");
    await store.action(second, "start");
    assert.equal(store.controlsFor(second)[0].icon, "stop");
    await store.action(second, "restart");
    assert.equal(JSON.stringify(config), before);
    assert.deepEqual(calls.filter(c => ["start", "stop", "restart"].includes(c.action)).map(c => [c.action, c.bot_id]),
        [["stop", "first"], ["start", "second"], ["restart", "second"]]);
    assert.equal(JSON.stringify(calls).includes("secret-"), false);

    const request = { request_id: "789:456:101", eligible: true };
    await store.accessAction(second, request, "approve", 3600);
    assert.deepEqual(calls.at(-1), { url: "/plugins/discord/discord_bridge_api", action: "approve", bot_id: "second", request_id: request.request_id, duration: 3600 });
    await store.accessAction(second, request, "approve", 0);
    assert.equal(calls.at(-1).duration, 0, "Until revoked must not become the default duration");
    const accessCalls = calls.length;
    context.projectName = "scoped";
    await store.accessAction(second, request, "approve");
    assert.equal(calls.length, accessCalls);
    context.projectName = "";
    second.token = "unsaved-token";
    await store.accessAction(second, request, "approve");
    assert.equal(calls.length, accessCalls);
    await store.accessAction(second, request, "revoke");
    assert.equal(calls.at(-1).action, "revoke");
    assert.equal(JSON.stringify(config).includes("auth_key"), false);
    context.addDiscordBot();
    const count = calls.length;
    await store.action(second, "restart");
    await store.action(config.bots[2], "start");
    context.projectName = "example-project";
    await store.action(second, "stop");
    assert.equal(calls.length, count);
    context.projectName = "";
    context.agentProfileKey = "example-profile";
    await store.action(second, "stop");
    assert.equal(calls.length, count);
    context.agentProfileKey = "";
    await store.action(second, "stop");
    assert.equal(calls.at(-1).bot_id, "second");

    let resolveStatus;
    pendingStatus = new Promise(resolve => { resolveStatus = resolve; });
    const refresh = store.refresh();
    store.cleanup();
    resolveStatus({ ok: true, bots: runtime });
    await refresh;
    assert.equal(timers.size, 0);
    assert.equal(store.bots.length, 0);
    assert.equal(store.loaded, false);
});
