import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as notifications } from "/components/notifications/notification-store.js";

const endpoint = "/plugins/discord/";
const notify = (type, message) => notifications.createNotification(type, message, "Discord");

function newBot() {
    return {
        id: crypto.randomUUID(), name: "", token: "", enabled: true, servers: [],
        chat_bridge: {
            auto_start: false, default_preset: "", default_agent_profile: "",
            allowed_users: [], allow_elevated: false, auth_key: "", session_timeout: 3600,
        },
    };
}

export const store = createStore("discordConfig", {
    bots: [], busy: false, busyBot: "", loaded: false, timer: null, generation: 0,
    settingsContext: null, savedDrafts: {},
    controls: [
        { action: "start", label: "Start bot", icon: "play_arrow" },
        { action: "stop", label: "Stop bot", icon: "stop" },
        { action: "restart", label: "Restart bot", icon: "refresh" },
    ],

    get scoped() {
        return !!(this.settingsContext?.projectName || this.settingsContext?.agentProfileKey);
    },

    runtime(bot) {
        return this.bots.find(item => item.id === bot.id);
    },

    changed(bot) {
        return JSON.stringify(bot) !== this.savedDrafts[bot.id];
    },

    disabledReason(bot, action) {
        if (this.scoped) return "Select Global and All profiles to control live bots.";
        if (this.busy || this.busyBot) return "A Discord request is in progress.";
        if (!this.loaded) return "Refresh bot status before using controls.";
        const saved = this.runtime(bot);
        if (!saved) return "Save this bot before using controls.";
        if (action === "stop") return saved.running ? "" : "This bot is already stopped.";
        if (this.changed(bot)) return "Save your changes before using this control.";
        if (!saved.enabled || !saved.configured) return "Save an enabled bot with a token first.";
        if (action === "start" && saved.running) return "This bot is already running.";
        return "";
    },

    statusLabel(bot) {
        if (this.scoped) return "Scoped settings";
        if (this.busyBot === bot.id) return "Working...";
        if (!this.loaded) return this.busy ? "Loading..." : "Status unavailable";
        const saved = this.runtime(bot);
        if (!saved) return "Save first";
        if (this.changed(bot)) return "Pending save";
        if (saved.status === "connected") return "Connected";
        if (saved.running) return "Connecting";
        if (!saved.enabled) return "Off";
        if (!saved.configured) return "Needs token";
        return saved.paused ? "Paused" : "Stopped";
    },

    async refresh(silent = false) {
        if (this.busy || this.busyBot || this.scoped) return;
        const generation = this.generation;
        this.busy = true;
        try {
            const data = await callJsonApi(endpoint + "discord_bridge_api", { action: "status" });
            if (generation !== this.generation) return;
            if (!data.ok) throw new Error(data.error);
            this.bots = data.bots;
            this.loaded = true;
        } catch (error) {
            if (generation !== this.generation) return;
            this.loaded = false;
            if (!silent) notify("error", error.message || "Could not load Discord bots.");
        } finally {
            if (generation === this.generation) this.busy = false;
        }
    },

    async action(bot, action) {
        if (!this.controls.some(control => control.action === action) || this.disabledReason(bot, action)) return;
        const generation = this.generation;
        this.busyBot = bot.id;
        try {
            const data = await callJsonApi(endpoint + "discord_bridge_api", {
                action, bot_id: bot.id,
            });
            if (generation !== this.generation) return;
            if (!data.ok) throw new Error(data.error);
            this.bots = this.bots.map(item => item.id === bot.id ? { ...item, ...data } : item);
        } catch (error) {
            if (generation === this.generation) notify("error", error.message || "Discord action failed.");
        } finally {
            if (generation === this.generation) this.busyBot = "";
        }
    },

    cleanup() {
        clearInterval(this.timer);
        this.timer = null;
        this.generation++;
        this.bots = [];
        this.savedDrafts = {};
        this.settingsContext = null;
        this.busy = false;
        this.busyBot = "";
        this.loaded = false;
    },

    async initConfig(config, context) {
        this.cleanup();
        const generation = this.generation;
        this.settingsContext = context;
        for (const key of ["bot", "user", "defaults", "memory", "persona", "polling", "chat_bridge"]) {
            config[key] ||= {};
        }
        if (config.bots == null) {
            const bot = newBot();
            Object.assign(bot, {
                id: "default", name: config.bot.name || "Main bot",
                token: config.bot.token || "", servers: config.servers || [],
                chat_bridge: { ...bot.chat_bridge, ...config.chat_bridge },
            });
            config.bots = [bot];
        }
        for (const bot of config.bots) {
            bot.chat_bridge = { ...newBot().chat_bridge, ...bot.chat_bridge };
            bot.servers ||= [];
            bot.enabled ??= true;
        }
        context.discordProfiles = [];
        context.addDiscordBot = () => config.bots.push(newBot());
        context.generateDiscordKey = async (bot) => {
            try {
                const data = await callJsonApi(endpoint + "discord_config_api", {
                    action: "generate_auth_key", bot_id: bot.id, draft: true,
                });
                if (generation !== this.generation) return;
                if (!data.auth_key) throw new Error(data.error);
                bot.chat_bridge.auth_key = data.auth_key;
                notify("info", "Auth key generated. Save settings to apply it.");
            } catch (error) { notify("error", error.message); }
        };
        context.copyDiscordKey = async (bot) => {
            try {
                await navigator.clipboard.writeText(bot.chat_bridge.auth_key || "");
                notify("success", "Auth key copied.");
            } catch (_) { notify("error", "Could not copy the auth key."); }
        };
        try {
            const data = await callJsonApi("agents", { action: "list" });
            if (generation !== this.generation) return;
            context.discordProfiles = data.data || [];
            for (const bot of config.bots) {
                const value = bot.chat_bridge.default_agent_profile || "";
                const profile = context.discordProfiles.find(p => p.key === value || p.label.toLowerCase() === value.toLowerCase());
                if (profile) bot.chat_bridge.default_agent_profile = profile.key;
            }
        } catch (_) { notify("error", "Could not load agent profiles. Existing selections are preserved."); }
        if (generation !== this.generation) return;
        this.savedDrafts = Object.fromEntries(config.bots.map(bot => [bot.id, JSON.stringify(bot)]));
        await this.refresh();
        if (generation === this.generation && !this.scoped) {
            this.timer = setInterval(() => this.refresh(true), 5000);
        }
    },
});
