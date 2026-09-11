import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as notifications } from "/components/notifications/notification-store.js";
import { store as pluginSettings } from "/components/plugins/plugin-settings-store.js";

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

export const store = createStore("discordDashboard", {
    bots: [], busy: false, loaded: false,

    async refresh() {
        if (this.busy) return;
        this.busy = true;
        try {
            const data = await callJsonApi(endpoint + "discord_bridge_api", { action: "status" });
            if (!data.ok) throw new Error(data.error);
            this.bots = data.bots;
            this.loaded = true;
        } catch (error) {
            notify("error", error.message || "Could not load Discord bots.");
        } finally {
            this.busy = false;
        }
    },

    async action(bot, action) {
        if (this.busy) return;
        this.busy = true;
        try {
            const data = await callJsonApi(endpoint + (action === "test" ? "discord_test" : "discord_bridge_api"), {
                action, bot_id: bot.id,
            });
            if (!data.ok) throw new Error(data.error);
            if (action === "test") notify("success", `Connected as ${data.user}.`);
            else Object.assign(bot, data);
        } catch (error) {
            notify("error", error.message || "Discord action failed.");
        } finally {
            this.busy = false;
        }
    },

    async configure() {
        try { await pluginSettings.openConfig("discord"); }
        catch (error) { notify("error", error.message); }
    },

    async initConfig(config, context) {
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
            context.discordProfiles = data.data || [];
            for (const bot of config.bots) {
                const value = bot.chat_bridge.default_agent_profile || "";
                const profile = context.discordProfiles.find(p => p.key === value || p.label.toLowerCase() === value.toLowerCase());
                if (profile) bot.chat_bridge.default_agent_profile = profile.key;
            }
        } catch (_) { notify("error", "Could not load agent profiles. Existing selections are preserved."); }
    },
});
